#!/usr/bin/env -S python3 -u
"""The gate's environment expands {root} and {home} in a team's [env], as v1 does for sessions (2026-11-08)."""
import importlib.machinery
import importlib.util
import sys
import tempfile
from pathlib import Path

HOME = Path(__file__).resolve().parents[2]
ld = importlib.machinery.SourceFileLoader("cl", str(HOME / "bin" / "codeteam-land"))
sp = importlib.util.spec_from_loader("cl", ld)
cl = importlib.util.module_from_spec(sp)
ld.exec_module(cl)

W = Path(tempfile.mkdtemp(prefix="land-env-"))
(W / "repo").mkdir()
(W / "team.toml").write_text(f'repo = "{W / "repo"}"\nworktree_root = "{W / "root"}"\n'
                             '[env]\nA = "{root}/acme/current"\nB = "{home}/x"\nC = "~/y"\n')
env = cl.team_env(cl.Team(str(W / "team.toml"), create=True))
root = cl.Team(str(W / "team.toml")).root
ok = env["A"] == f"{root}/acme/current" and env["B"] == f"{root}/team/x" and env["C"] == str(Path.home() / "y")
print(("  PASS" if ok else "  FAIL") + " {root}, {home} and ~ are expanded", "" if ok else (env["A"], env["B"], env["C"]))
sys.exit(0 if ok else 1)
