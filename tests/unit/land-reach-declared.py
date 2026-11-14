#!/usr/bin/env -S python3 -u
"""Reach from declared lane deps in a repo with no package manifests: a lane that
declares `deps` is reached by its own folders, files and globs and by the zones it names, not by every change; a lane
without deps, or naming a zone that does not exist, keeps the whole tree. A throwaway tree with no Package.swift or
Cargo.toml anywhere."""
import importlib.machinery
import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

HOME = Path(__file__).resolve().parents[2]
ld = importlib.machinery.SourceFileLoader("cl", str(HOME / "bin" / "codeteam-land"))
sp = importlib.util.spec_from_loader("cl", ld)
cl = importlib.util.module_from_spec(sp)
sys.modules["cl"] = cl
ld.exec_module(cl)
W = Path(tempfile.mkdtemp(prefix="reach-declared-"))
fails = 0


def t(label, cond, detail=""):
    global fails
    print(("  PASS " if cond else "  FAIL ") + label + ("" if cond else f"  [{detail}]"))
    fails += not cond


T = W / "tree"
for f in ("zone/zone.mk", "bin/codeteam-land", "tests/unit/land-a.py", "roles/zone.md", "bin/codeteam",
          "v2/loop.py", "old/x.sh", "README.md"):
    (T / f).parent.mkdir(parents=True, exist_ok=True)
    (T / f).write_text("x\n")
LANES = {
    "pipeline": 'path = "zone"\nowns = ["bin/codeteam-land", "tests/unit/land-*.py"]\ndeps = []\n',
    "runtime": 'path = "roles"\nowns = ["bin/codeteam"]\ndeps = ["pipeline"]\n',     # runtime calls pipeline
    "loop": 'path = "v2"\ndeps = ["runtime"]\n',                                     # loop calls runtime
    "legacy": 'path = "old"\n',                                                      # declares nothing
}


def team(lanes=LANES, **land):
    body = "".join(f'[[lanes]]\nname = "{n}"\n{v}' for n, v in lanes.items())
    extra = "".join(f'{k} = "{v}"\n' for k, v in land.items())
    (W / "team.toml").write_text(f'repo = "{T}"\nworktree_root = "{W / "root"}"\n{body}[land]\n{extra}')
    return cl.Team(str(W / "team.toml"), create=False)


tm = team()
r = cl.reach(tm, str(T), ["bin/codeteam-land"])
t("an owned file: its lane, the lane that names it, and the lane that declares nothing; not loop (calls runtime)",
  r == ["legacy", "pipeline", "runtime"], r)
r = cl.reach(tm, str(T), ["tests/unit/land-a.py"])
t("a file an owned glob matches reaches as the owned file does", r == ["legacy", "pipeline", "runtime"], r)
r = cl.reach(tm, str(T), ["v2/loop.py"])
t("a lane's own folder: that lane and the lane that declares nothing", r == ["legacy", "loop"], r)
r = cl.reach(tm, str(T), ["README.md"])
t("a file only the whole-tree lane holds reaches that lane, as a package team's whole-repo lane does",
  r == ["legacy"], r)
r = cl.reach(team({n: v for n, v in LANES.items() if n != "legacy"}), str(T), ["README.md"])
t("when every lane declares deps, a file no lane owns reaches every zone", r == ["loop", "pipeline", "runtime"], r)
r = cl.reach(team(reach="chain"), str(T), ["bin/codeteam-land"])
t('reach = "chain" follows the names through: loop too', r == ["legacy", "loop", "pipeline", "runtime"], r)
bad = dict(LANES, runtime='path = "roles"\nowns = ["bin/codeteam"]\ndeps = ["nope"]\n')
r = cl.reach(team(bad), str(T), ["v2/loop.py"])
t("a lane naming a zone that does not exist keeps the whole tree", r == ["legacy", "loop", "runtime"], r)
plain = {n: "\n".join(x for x in v.splitlines() if not x.startswith("deps")) + "\n" for n, v in LANES.items()}
r = cl.reach(team(plain), str(T), ["v2/loop.py"])
t("with no deps declared anywhere, every change reaches every zone, as before",
  r == ["legacy", "loop", "pipeline", "runtime"], r)

if fails:
    print(f"\n{fails} failed  ({W} kept for a look)")
else:
    shutil.rmtree(W, ignore_errors=True)
    print("\nall passed")
sys.exit(1 if fails else 0)
