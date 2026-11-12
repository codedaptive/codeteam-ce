#!/usr/bin/env -S python3 -u
"""install-hook makes append-only logs merge by union in every worktree (2026-11-08). A throwaway repo."""
import os, subprocess, sys, tempfile
from pathlib import Path
LAND = str(Path(__file__).resolve().parents[2] / "bin" / "codeteam-land")
W = Path(tempfile.mkdtemp(prefix="land-union-")); R = W / "repo"; R.mkdir()
def sh(c, cwd=R): return subprocess.run(c, shell=True, cwd=cwd, capture_output=True, text=True)
sh("git init -q -b main && printf 'a\\n' > DECISIONS.md && git add -A && git -c user.email=t@t -c user.name=t commit -qm i && git branch integration")
(W / "team.toml").write_text(f'repo = "{R}"\nintegration = "integration"\nworktree_root = "{W / "team"}"\n[[lanes]]\nname = "A"\npath = "A"\n[land]\ncheck = ""\n')
subprocess.run([LAND, str(W / "team.toml"), "install-hook"], capture_output=True, env={k: v for k, v in os.environ.items() if not k.startswith("CODETEAM_")})
sh(f"git worktree add -q -b x {W / 'x'} main")
sh("echo b >> DECISIONS.md && git -c user.email=t@t -c user.name=t commit -qam b", cwd=W / "x")
sh("git checkout -q -b y && echo c >> DECISIONS.md && git -c user.email=t@t -c user.name=t commit -qam c")
r = sh("git -c user.email=t@t -c user.name=t merge -q --no-edit x")
ok = r.returncode == 0 and (R / "DECISIONS.md").read_text().split() == ["a", "c", "b"]
print(("  PASS " if ok else "  FAIL ") + "two entries added at the end in two worktrees merge without a clash", "" if ok else r.stdout + r.stderr)
attrs = (R / ".git" / "info" / "attributes")
attrs.write_text(attrs.read_text().replace("CHANGELOG.md merge=union\n", "CHANGELOG.md merge=union\nRULINGS.md merge=union\n", 1))
subprocess.run([LAND, str(W / "team.toml"), "install-hook"], capture_output=True, env={k: v for k, v in os.environ.items() if not k.startswith("CODETEAM_")})
r2 = sh("git check-attr merge -- docs/RULINGS.md docs/CHANGELOG.md").stdout
ok2 = "RULINGS.md: merge: unspecified" in r2 and "CHANGELOG.md: merge: union" in r2 and attrs.read_text().count("merge=union") == 3
print(("  PASS " if ok2 else "  FAIL ") + "install-hook rewrites an old list: RULINGS.md comes off", "" if ok2 else r2 + attrs.read_text())
ok = ok and ok2
print("all passed" if ok else "failed"); sys.exit(0 if ok else 1)
