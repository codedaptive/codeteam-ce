#!/usr/bin/env -S python3 -u
"""codeteam-land and codeteam fixes, second set (2026-11-08): land-cancel, wo-retire, one
toolchain stream, the guard letting git pack refs, team.json's lanes following the manifest. A throwaway repo."""
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BIN = Path(__file__).resolve().parents[2] / "bin"
LAND = str(BIN / "codeteam-land")


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


cl = load("cl", LAND)
W = Path(tempfile.mkdtemp(prefix="land-fixes-b-"))
REPO, ROOT = W / "repo", W / "team"
fails = 0


def t(label, cond, detail=""):
    global fails
    print(("  PASS " if cond else "  FAIL ") + label + ("" if cond else f"  [{detail}]"))
    fails += not cond


def sh(cmd, cwd=REPO, check=True):
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"setup failed: {cmd}\n{r.stdout}{r.stderr}")
    return r


def land(*args, env=None):
    e = {k: v for k, v in os.environ.items() if not k.startswith("CODETEAM_")}
    # Keep home-scoped state inside the fixture, including logs from any stray land-check.
    e["HOME"] = str(W / "home")
    # That HOME has no .gitconfig, and git refuses even a conflicting merge without a committer identity.
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@t"), ("GIT_COMMITTER_NAME", "t"),
                 ("GIT_COMMITTER_EMAIL", "t@t")):
        e.setdefault(k, v)
    e.update(env or {})
    return subprocess.run([LAND, str(W / "team.toml"), *args], capture_output=True, text=True, env=e)


REPO.mkdir()
(REPO / "A").mkdir()
(REPO / "A" / "value").write_text("1\n")
sh("git init -q -b main && git add -A && git -c user.email=t@t -c user.name=t commit -qm init && git branch integration && git branch landing")
(W / "team.toml").write_text(f'''repo = "{REPO}"
integration = "integration"
worktree_root = "{ROOT}"
[[lanes]]
name = "A"
path = "A"
[land]
check = ""
test = "true"
gates = ""
notify = "echo {{kind}} {{to}} {{text}} >> {W / 'notify.log'}"
owner_notify = "true"
''')
land("install-hook")
print("== the guard still refuses deleting a guarded branch")
r = sh("git update-ref -d refs/heads/integration", check=False)
t("deleting integration is refused", r.returncode != 0 and sh("git rev-parse -q --verify integration",
                                                                check=False).returncode == 0, (r.returncode, r.stderr, sh("git config --get-regexp hook", check=False).stdout))

r = sh("git -c x.y=pack-refs update-ref -d refs/heads/integration", check=False)
t("a deletion with pack-refs in its arguments is still refused", r.returncode != 0, r.stderr)

print("== land-cancel and wo-retire")
tree = Path(land("wo-cut", "A", "w1").stdout.strip())
(tree / "A" / "value").write_text("2\n")
sh("git add -A && git -c user.email=t@t -c user.name=l commit -qm w1", cwd=tree)
land("land", "w1")
t("wo-retire refuses a queued work order", land("wo-retire", "w1").returncode != 0)
r = land("land-cancel", "w1", "--reason", "test")
t("land-cancel takes it out of the queue", r.returncode == 0 and "w1" not in land("queue").stdout, r.stdout + r.stderr)
time.sleep(1)
t("its zone is told", "taken out of the landing queue" in (W / "notify.log").read_text())
(tree / "A" / "new_work.py").write_text("x = 1\n")
t("wo-retire refuses a tree with an untracked file, without --force", land("wo-retire", "w1").returncode != 0 and
  (tree / "A" / "new_work.py").exists())
(tree / "A" / "new_work.py").unlink()
r = land("wo-retire", "w1")
t("wo-retire removes the tree and keeps the branch as refs/archive/wo/w1",
  r.returncode == 0 and not tree.exists() and sh("git rev-parse refs/archive/wo/w1", check=False).returncode == 0,
  r.stdout + r.stderr)

print("== the toolchain fingerprint: one stream, as land-check")
cmd = "echo out; echo err >&2; echo out2"
want = hashlib.sha1(subprocess.run(["sh", "-c", f"sh -c '{cmd}' 2>&1"], capture_output=True).stdout).hexdigest()[:16]
t("toolchain_fp hashes stdout and stderr as one stream", cl.toolchain_fp({"toolchain": [cmd]}) == want)

print("== the guard lets git pack refs, and still refuses a deletion")
r = sh("git pack-refs --all", check=False)
t("git pack-refs --all runs with the guard installed", r.returncode == 0, r.stderr)

print("== team.json's lanes follow the manifest at every render")
ct = load("ct", BIN / "codeteam")
m = W / "ct.toml"
m.write_text(f'product = "x"\nrepo = "{REPO}"\nbase = "main"\nworktree_root = "{W / "ctroot"}"\n'
             '[[lanes]]\nname = "A"\npath = "."\nowns = ["A"]\n')
ctt = ct.Team(str(m))
ctt.team_file.parent.mkdir(parents=True, exist_ok=True)
ctt.team_file.write_text(json.dumps({"product": "x", "lanes": {"A": {"path": ".", "owns": ["src/old"], "job": "",
                                                                     "test": "", "role": "zone", "guide": ""}}}))
team_json = json.loads(ctt.team_file.read_text())
ct.sync_lanes(ctt, team_json)
t("a lane's stale owns in team.json become the manifest's", json.loads(ctt.team_file.read_text())["lanes"]["A"]["owns"]
  == ["A"] and team_json["lanes"]["A"]["owns"] == ["A"], ctt.team_file.read_text())

print(f"\n{'all passed' if not fails else f'{fails} failed'}  ({W})")
sys.exit(1 if fails else 0)
