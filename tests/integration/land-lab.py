#!/usr/bin/env -S python3 -u
"""codeteam-land for a lab team (mode = "lab": base is its integration, checked out in the base checkout) with the
validation suite in a local clone ([land.validate], no second machine). Nothing outside a temp folder is touched."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

LAND = str(Path(__file__).resolve().parents[2] / "bin" / "codeteam-land")
W = Path(tempfile.mkdtemp(prefix="land-lab-"))
REPO, ROOT = W / "repo", W / "team"
fails = 0


def sh(cmd, cwd=REPO, check=True):
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"setup failed: {cmd}\n{r.stdout}{r.stderr}")
    return r


def t(label, cond, detail=""):
    global fails
    print(("  PASS " if cond else "  FAIL ") + label + ("" if cond else f"  [{detail}]"))
    fails += not cond


def land(*args, env=None):
    e = {k: v for k, v in os.environ.items() if k != "CODETEAM_SESSION"}
    # The validation clone's land-check keeps its log under HOME; keep it inside the fixture.
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
(REPO / "notes.md").write_text("orchestrator's notes\n")
sh("git init -q -b main && git add -A && git -c user.email=t@t -c user.name=t commit -qm init && git branch lane/A")
sh(f"git worktree add -q {ROOT / 'workcrews/A/repo-main-A'} lane/A")
(W / "team.toml").write_text(f'''mode = "lab"
repo = "{REPO}"
base = "main"
lane_branch_prefix = "lane/"
worktree_root = "{ROOT}"
[[lanes]]
name = "A"
path = "A"
[land]
check = ""
test = "true"
gates = ""
seed_index = false
interface = false
notify = "echo {{kind}} {{to}} {{text}} >> {W / 'notify.log'}"
owner_notify = "true"
[land.validate]
local = true
path = "{W / 'validate'}"
suite = "test $(cat A/value) -lt 50"
toolchain = ["echo same"]
''')
land("install-hook")
t("alpha-install for a local validate tier creates its clone", land("alpha-install").returncode == 0 and
  (W / "validate" / ".git" / "land-check").exists(), land("alpha-install").stderr)

print("== a lab team lands on base, in its base checkout")
(REPO / "notes.md").write_text("orchestrator's notes, edited and not committed\n")
tree = Path(land("wo-cut", "A", "w1").stdout.strip())
(tree / "A" / "value").write_text("2\n")
sh("git add -A && git -c user.email=t@t -c user.name=l commit -qm w1", cwd=tree)
land("land", "w1")
r = land("reviewed", "w1", env={"CODETEAM_SESSION": "Kong"})
assert r.returncode == 0, r.stdout + r.stderr
land("queue-run", "--once")
t("main moved by fast-forward and the base checkout's files follow", sh("git show main:A/value").stdout.strip() == "2"
  and (REPO / "A" / "value").read_text().strip() == "2", sh("git log --oneline -2").stdout)
t("the orchestrator's uncommitted edit in another file is kept", "not committed" in (REPO / "notes.md").read_text())
t("a direct move of main is refused by the hook", sh("git -c user.email=t@t -c user.name=t commit -q --allow-empty -m x",
                                                      check=False).returncode != 0)

print("== the local validation suite")
r = land("validate-run", "--once")
rows = [json.loads(line) for line in (ROOT / "land" / "validation-results.jsonl").read_text().splitlines()]
t("the reviewed landing is checked in the local clone and passes", r.returncode == 0 and len(rows) == 1
  and rows[0]["commit"] == sh("git rev-parse main").stdout.strip() and rows[0]["result"] == "pass", rows)
t("the pass has a per-test validation result", rows[0]["tests"][0]["name"] == "suite"
  and rows[0]["tests"][0]["result"] == "pass", rows)

print("== migrate on a lab layout")
r = land("migrate", "plan")
t("plan runs with base as exchange and integration", r.returncode == 0 and "1 standing lane worktrees" in r.stdout, r.stdout + r.stderr)
r = land("migrate", "retire")
t("retire removes the lane worktree and never the base checkout", r.returncode == 0 and REPO.exists() and
  not (ROOT / "workcrews/A/repo-main-A").exists(), r.stdout + r.stderr)

print("== the default tier for a landing team without one")
import importlib.machinery, importlib.util
loader = importlib.machinery.SourceFileLoader("cl", LAND)
spec = importlib.util.spec_from_loader("cl", loader); cl = importlib.util.module_from_spec(spec); loader.exec_module(cl)
(W / "bare.toml").write_text(f'repo = "{REPO}"\nworktree_root = "{W / "t2"}"\n[[lanes]]\nname = "A"\npath = "A"\n[land]\nenabled = true\n')
a = cl.alpha_cfg(cl.Team(str(W / "bare.toml"), create=False))
t("enabled with no tier: a local clone running validate-suite at class full", a and a.get("local")
  and "validate-suite" in a["suite"] and a.get("steps") is True, a)

print(f"\n{'all passed' if not fails else f'{fails} failed'}  ({W})")
sys.exit(1 if fails else 0)
