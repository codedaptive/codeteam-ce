#!/usr/bin/env -S python3 -u
"""Contract files (spec v5 §4): a file listed in [land.contracts] reaches its consumer zones. A throwaway repo."""
import importlib.machinery, importlib.util, subprocess, sys, tempfile
from pathlib import Path
LAND = str(Path(__file__).resolve().parents[2] / "bin" / "codeteam-land")
ld = importlib.machinery.SourceFileLoader("cl", LAND); sp = importlib.util.spec_from_loader("cl", ld)
cl = importlib.util.module_from_spec(sp); ld.exec_module(cl)
W = Path(tempfile.mkdtemp(prefix="land-contracts-")); R = W / "repo"
for p in ("A/schema/events.json", "A/x.py", "B/y.py", "C/z.py", "A/Cargo.toml", "B/Cargo.toml", "C/Cargo.toml"):
    (R / p).parent.mkdir(parents=True, exist_ok=True); (R / p).write_text("1\n")
subprocess.run("git init -q -b main && git add -A && git -c user.email=t@t -c user.name=t commit -qm i && git branch integration",
               shell=True, cwd=R, capture_output=True)
(W / "team.toml").write_text(f'''repo = "{R}"
integration = "integration"
worktree_root = "{W / "team"}"
[[lanes]]
name = "A"
path = "A"
[[lanes]]
name = "B"
path = "B"
[[lanes]]
name = "C"
path = "C"
[land.contracts]
"A/schema/*.json" = ["B"]
''')
team = cl.Team(str(W / "team.toml"), create=True)
fails = 0
for label, files, want in (("a contract file reaches its consumers", ["A/schema/events.json"], ["A", "B"]),
                           ("any other file in the zone does not", ["A/x.py"], ["A"])):
    got = cl.reach(team, str(R), files)
    ok = got == want; fails += not ok
    print(("  PASS " if ok else "  FAIL ") + label + ("" if ok else f"  [{got}]"))
print("all passed" if not fails else f"{fails} failed"); sys.exit(1 if fails else 0)
