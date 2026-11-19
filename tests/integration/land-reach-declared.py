#!/usr/bin/env -S python3 -u
"""Reach from declared lane deps in a repo with no package manifests: a lane that
declares `deps` is reached by its own folders, files and globs and by the zones it names, not by every change; a lane
without deps, or naming a zone that does not exist, keeps the whole tree for a code entry; an entry of documents
alone is its own scope either way. A throwaway tree with no Package.swift or Cargo.toml anywhere, as
a v5.5 checkout's, and a second tree of two packages for the documents cases."""
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
          "v2/loop.py", "old/x.sh", "README.md", "Makefile"):
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
t("a test file an owned glob matches reaches only its owner", r == ["pipeline"], r)
r = cl.reach(tm, str(T), ["v2/loop.py"])
t("a lane's own folder: that lane and the lane that declares nothing", r == ["legacy", "loop"], r)
r = cl.reach(tm, str(T), ["README.md"])
t("a file only the whole-tree lane holds reaches that lane, as a package team's whole-repo lane does",
  r == ["legacy"], r)
declared_team = team({n: v for n, v in LANES.items() if n != "legacy"})
r = cl.reach(declared_team, str(T), ["Makefile"])
t("when every lane declares deps, a file no lane owns reaches every zone", r == ["loop", "pipeline", "runtime"], r)
r = cl.reach(declared_team, str(T), ["README.md"])
t("an unowned documentation file reaches no zone", r == [], r)
r = cl.reach(team(reach="chain"), str(T), ["bin/codeteam-land"])
t('reach = "chain" follows the names through: loop too', r == ["legacy", "loop", "pipeline", "runtime"], r)
bad = dict(LANES, runtime='path = "roles"\nowns = ["bin/codeteam"]\ndeps = ["nope"]\n')
r = cl.reach(team(bad), str(T), ["v2/loop.py"])
t("a lane naming a zone that does not exist keeps the whole tree", r == ["legacy", "loop", "runtime"], r)
plain = {n: "\n".join(x for x in v.splitlines() if not x.startswith("deps")) + "\n" for n, v in LANES.items()}
r = cl.reach(team(plain), str(T), ["v2/loop.py"])
t("with no deps declared anywhere, every change reaches every zone, as before",
  r == ["legacy", "loop", "pipeline", "runtime"], r)

D = W / "docscope-tree"
for f in ("packages/other/Package.swift", "packages/other/Sources/a.swift",
          "packages/owner/Package.swift", "docs/specs/z/nested/plan.md", "PLUGIN_X.md", "scripts/run.sh",
          "notes/guide.txt", "mixed/plan.md", "mixed/run.sh", "mixed-deep/plan.md", "mixed-deep/sub/run.sh",
          "mixed-hidden/plan.md", "mixed-hidden/.gitkeep"):
    (D / f).parent.mkdir(parents=True, exist_ok=True)
    (D / f).write_text("x\n")
(D / "docs" / "empty").mkdir(parents=True)
for label, owned, changed, expected, land, owner_deps in (
    ("declared docs-only folder does not reach another package", "docs/specs/z", "packages/other/Sources/a.swift", ["other"], "", 'deps = []\n'),
    ("declared owned document file does not reach another package", "PLUGIN_X.md", "packages/other/Sources/a.swift", ["other"], "", 'deps = []\n'),
    ("declared manifestless code folder stays scoped", "scripts", "packages/other/Sources/a.swift", ["other"], "", 'deps = []\n'),
    ("undeclared manifestless code folder reaches another package", "scripts", "packages/other/Sources/a.swift", ["other", "owner"], "", ""),
    ("declared mixed folder stays scoped", "mixed", "packages/other/Sources/a.swift", ["other"], "", 'deps = []\n'),
    ("declared mixed folder with nested code stays scoped", "mixed-deep", "packages/other/Sources/a.swift", ["other"], "", 'deps = []\n'),
    ("declared mixed folder with hidden file stays scoped", "mixed-hidden", "packages/other/Sources/a.swift", ["other"], "", 'deps = []\n'),
    ("undeclared mixed folder reaches another package", "mixed", "packages/other/Sources/a.swift", ["other", "owner"], "", ""),
    ("declared nested document change reaches folder owner", "docs/specs/z", "docs/specs/z/nested/plan.md", ["owner"], "", 'deps = []\n'),
    ("declared owned document change reaches file owner", "PLUGIN_X.md", "PLUGIN_X.md", ["owner"], "", 'deps = []\n'),
    ("declared empty docs folder does not reach another package", "docs/empty", "packages/other/Sources/a.swift", ["other"], "", 'deps = []\n'),
    ("declared configured suffix does not reach another package", "notes", "packages/other/Sources/a.swift", ["other"],
     '[land]\ndocs_only_suffixes = [".txt"]\n', 'deps = []\n'),
):
    (W / "docscope-team.toml").write_text(
        f'repo = "{D}"\nworktree_root = "{W / "root"}"\n'
        '[[lanes]]\nname = "other"\npath = "packages/other"\ndeps = []\n'
        f'[[lanes]]\nname = "owner"\npath = "packages/owner"\nowns = ["{owned}"]\n{owner_deps}{land}')
    doc_team = cl.Team(str(W / "docscope-team.toml"), create=False)
    r = cl.reach(doc_team, str(D), [changed])
    t(label, r == expected, r)

if fails:
    print(f"\n{fails} failed  ({W} kept for a look)")
else:
    shutil.rmtree(W, ignore_errors=True)
    print("\nall passed")
sys.exit(1 if fails else 0)
