#!/usr/bin/env -S python3 -u
"""The gate's reach is direct: change X and B calls X, test X and B, not A, which calls B.
A throwaway tree of path-dependent packages."""
import importlib.machinery
import importlib.util
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
print(f"\n{'all passed' if not fails else f'{fails} failed'}  ({W})")
sys.exit(1 if fails else 0)
