#!/usr/bin/env -S python3 -u
"""The gate's reach is direct: change X and B calls X, test X and B, not A, which calls B.
A throwaway tree of path-dependent packages."""
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
W = Path(tempfile.mkdtemp(prefix="reach-direct-"))
fails = 0


def t(label, cond, detail=""):
    global fails
    print(("  PASS " if cond else "  FAIL ") + label + ("" if cond else f"  [{detail}]"))
    fails += not cond


T = W / "tree"
pk = {"libs/X": [], "kits/B": ["../../libs/X"], "apps/A": ["../../kits/B"]}
for d, deps in pk.items():
    (T / d / "Sources").mkdir(parents=True)
    (T / d / "Package.swift").write_text("let p = Package(dependencies: [" +
                                         ", ".join(f'.package(path: "{x}")' for x in deps) + "])\n")
    (T / d / "Sources" / "a.swift").write_text("let x = 1\n")
(T / "libs" / "R" / "rust").mkdir(parents=True)              # a Rust-only lib: its manifest one folder down
(T / "libs" / "R" / "rust" / "Cargo.toml").write_text('[dependencies]\nx = { path = "../../X" }\n')
(T / "Makefile").write_text("all:\n")
(W / "team.toml").write_text(f'repo = "{T}"\nworktree_root = "{W / "root"}"\n'
                             '[[lanes]]\npath = "libs/X"\n[[lanes]]\npath = "kits/B"\n[[lanes]]\npath = "apps/A"\n'
                             '[[lanes]]\npath = "libs/R"\n[[lanes]]\nname = "gone"\npath = "kits/Gone"\n')
team = cl.Team(str(W / "team.toml"), create=False)
team.zones["gone"] = ["kits/Gone"]                           # a zone with nothing in this tree
r = cl.reach(team, str(T), ["libs/X/Sources/a.swift"])
t("change X: X, B (calls X) and R (its rust/ calls X); not A (calls B)", r == ["B", "R", "X"], r)
r = cl.reach(team, str(T), ["kits/B/Sources/a.swift"])
t("change B: B and A", r == ["A", "B"], r)
r = cl.reach(team, str(T), ["Makefile"])
t("a file in no zone reaches every zone with something in the tree", r == ["A", "B", "R", "X"], r)
team.cfg["reach"] = "chain"
r = cl.reach(team, str(T), ["libs/X/Sources/a.swift"])
t('reach = "chain" follows through again: A too', r == ["A", "B", "R", "X"], r)
# Separate teams keep each owned entry's scope from masking the others.
D = W / "docscope-tree"
for f in ("packages/other/Package.swift", "packages/other/Sources/a.swift",
          "packages/owner/Package.swift", "docs/specs/z/nested/plan.md", "PLUGIN_X.md", "scripts/run.sh",
          "notes/guide.txt", "mixed/plan.md", "mixed/run.sh", "mixed-deep/plan.md", "mixed-deep/sub/run.sh",
          "mixed-hidden/plan.md", "mixed-hidden/.gitkeep"):
    (D / f).parent.mkdir(parents=True, exist_ok=True)
    (D / f).write_text("x\n")
(D / "docs" / "empty").mkdir(parents=True)
for label, owned, changed, expected, land in (
    ("docs-only folder does not reach another package", "docs/specs/z", "packages/other/Sources/a.swift", ["other"], ""),
    ("owned document file does not reach another package", "PLUGIN_X.md", "packages/other/Sources/a.swift", ["other"], ""),
    ("manifestless code folder reaches another package", "scripts", "packages/other/Sources/a.swift", ["other", "owner"], ""),
    ("mixed folder reaches another package", "mixed", "packages/other/Sources/a.swift", ["other", "owner"], ""),
    ("mixed folder with nested code reaches another package", "mixed-deep", "packages/other/Sources/a.swift", ["other", "owner"], ""),
    ("mixed folder with hidden file reaches another package", "mixed-hidden", "packages/other/Sources/a.swift", ["other", "owner"], ""),
    ("nested document change reaches folder owner", "docs/specs/z", "docs/specs/z/nested/plan.md", ["owner"], ""),
    ("owned document change reaches file owner", "PLUGIN_X.md", "PLUGIN_X.md", ["owner"], ""),
    ("empty docs folder does not reach another package", "docs/empty", "packages/other/Sources/a.swift", ["other"], ""),
    ("configured document suffix does not reach another package", "notes", "packages/other/Sources/a.swift", ["other"],
     '[land]\ndocs_only_suffixes = [".txt"]\n'),
):
    (W / "docscope-team.toml").write_text(
        f'repo = "{D}"\nworktree_root = "{W / "root"}"\n'
        '[[lanes]]\nname = "other"\npath = "packages/other"\n'
        f'[[lanes]]\nname = "owner"\npath = "packages/owner"\nowns = ["{owned}"]\n{land}')
    doc_team = cl.Team(str(W / "docscope-team.toml"), create=False)
    r = cl.reach(doc_team, str(D), [changed])
    t(label, r == expected, r)

if fails:
    print(f"\n{fails} failed  ({W} kept for a look)")
else:
    shutil.rmtree(W, ignore_errors=True)
    print("\nall passed")
sys.exit(1 if fails else 0)
