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
# A product that sets its own changelog merge policy keeps it: a product that unions only its feature logs had
# codeteam's CHANGELOG.md and *_CHANGELOG.md lines in info/attributes override the rest.
R3 = W / "repo3"; R3.mkdir()
(R3 / ".gitattributes").write_text("**/docs/CHANGELOG.md merge=union\n*.png binary\n")
c = sh("git init -q -b main && git add -A && git -c user.email=t@t -c user.name=t commit -qm i && git branch integration",
       cwd=R3)
assert c.returncode == 0, c.stdout + c.stderr
(W / "team3.toml").write_text((W / "team.toml").read_text().replace(str(R), str(R3)).replace(str(W / "team"), str(W / "team3")))
subprocess.run([LAND, str(W / "team3.toml"), "install-hook"], capture_output=True, env={k: v for k, v in os.environ.items() if not k.startswith("CODETEAM_")})
r3 = sh("git check-attr merge -- CHANGELOG.md docs/reference/X_SPEC_CHANGELOG.md docs/CHANGELOG.md DECISIONS.md", cwd=R3).stdout
want = ["CHANGELOG.md: merge: unspecified", "docs/reference/X_SPEC_CHANGELOG.md: merge: unspecified",
        "docs/CHANGELOG.md: merge: union", "DECISIONS.md: merge: union"]
attrs3 = R3 / ".git" / "info" / "attributes"
ok3 = r3.splitlines() == want and attrs3.exists() and "CHANGELOG" not in attrs3.read_text()
print(("  PASS " if ok3 else "  FAIL ") + "a product's own changelog merge policy stands; codeteam unions DECISIONS.md only",
      "" if ok3 else r3 + (attrs3.read_text() if attrs3.exists() else "(no info/attributes)"))
ok = ok and ok2 and ok3
print("all passed" if ok else "failed"); sys.exit(0 if ok else 1)
