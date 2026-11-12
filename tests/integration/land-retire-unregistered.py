#!/usr/bin/env -S python3 -u
"""Check work-order retirement without records and team manifest validation."""
import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HOME = Path(__file__).resolve().parents[2]
LAND = str(HOME / "bin" / "codeteam-land")
ld = importlib.machinery.SourceFileLoader("cl", LAND)
sp = importlib.util.spec_from_loader("cl", ld)
cl = importlib.util.module_from_spec(sp)
sys.modules["cl"] = cl
ld.exec_module(cl)
W = Path(tempfile.mkdtemp(prefix="small-three-"))
REPO, ROOT = W / "repo", W / "team"
fails = 0


def t(label, cond, detail=""):
    global fails
    print(("  PASS " if cond else "  FAIL ") + label + ("" if cond else f"  [{detail}]"))
    fails += not cond


def land(*args):
    e = {k: v for k, v in os.environ.items() if not k.startswith("CODETEAM_")}
    e["CODETEAM_SESSION"] = "orc"
    return subprocess.run([LAND, str(W / "team.toml"), *args], capture_output=True, text=True, env=e)


(REPO / "A").mkdir(parents=True)
(REPO / "A" / "x").write_text("1\n")
subprocess.run("git init -q -b main && git add -A && git -c user.email=t@t -c user.name=t commit -qm i && git branch integration",
               shell=True, cwd=REPO)
(W / "team.toml").write_text(f'''repo = "{REPO}"
integration = "integration"
worktree_root = "{ROOT}"
[[lanes]]
name = "A"
path = "A"
[land]
check = ""
gates = ""
notify = "true"
''')

print("== wo-cut and wo-retire")
r = land("wo-cut", "A", "w1")
t("wo-cut returns a tree with its record written", r.returncode == 0 and (ROOT / "land" / "wo" / "w1.json").exists(), r.stderr)
(ROOT / "wo" / "A" / "ghost").mkdir(parents=True)
(ROOT / "wo" / "A" / "ghost" / "f").write_text("x")
r = land("wo-retire", "ghost")
t("a folder with no record that is not a git worktree needs --force", r.returncode != 0 and "--force" in r.stderr, r.stderr)
r = land("wo-retire", "ghost", "--force")
t("with --force it is removed and recorded as retired", r.returncode == 0 and not (ROOT / "wo" / "A" / "ghost").exists()
  and (ROOT / "land" / "wo" / "ghost.retired.json").exists(), r.stdout + r.stderr)
subprocess.run(["git", "worktree", "add", "-q", "-b", "wo/A/half", str(ROOT / "wo" / "A" / "half"), "integration"], cwd=REPO)
r = land("wo-retire", "half")
t("a git tree with no record is retired like any work order, its branch archived", r.returncode == 0
  and not (ROOT / "wo" / "A" / "half").exists()
  and subprocess.run(["git", "rev-parse", "-q", "--verify", "refs/archive/wo/half"], cwd=REPO, capture_output=True).returncode == 0,
  r.stdout + r.stderr)
t("a name with no folder is still unknown", land("wo-retire", "nothing").returncode != 0)

print("== manifests")
r = subprocess.run([str(HOME / "bin" / "codeteam-check-manifests")], capture_output=True, text=True)
t("every teams/*.toml of this checkout loads", r.returncode == 0, r.stdout[-400:])
bad = W / "bad"
bad.mkdir()
(bad / "x.toml").write_text('repo = "/tmp"\nmode = "lab"\n[[assistants]]\nname = "N"\ntier = "integration"\n')
r = subprocess.run([str(HOME / "bin" / "codeteam-check-manifests"), str(bad)], capture_output=True, text=True)
t("a manifest that cannot load is named, exit 1", r.returncode == 1 and "FAIL x.toml" in r.stdout, r.stdout)
print(f"\n{'all passed' if not fails else f'{fails} failed'}  ({W})")
sys.exit(1 if fails else 0)
