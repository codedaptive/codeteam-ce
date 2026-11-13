#!/usr/bin/env -S python3 -u
"""wo-cut replaces a branch an earlier cut left with no record and no tree when it holds nothing beyond integration,
keeping it as refs/archive/wo/<wo>; a branch with commits of its own is refused (2026-11-11: a cut that
died on a full disk left its wo/<zone>/<wo> branch and the next cut failed). Real git, the real
CLI, a throwaway team."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

LAND = str(Path(__file__).resolve().parents[2] / "bin" / "codeteam-land")
W = Path(tempfile.mkdtemp(prefix="land-wo-cut-"))
REPO, ROOT = W / "repo", W / "team"
G = ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(REPO)]
fails = 0


def t(label, cond, detail=""):
    global fails
    print(("  PASS " if cond else "  FAIL ") + label + ("" if cond else f"  [{detail}]"))
    fails += not cond


def land(*args):
    env = {k: v for k, v in os.environ.items() if k != "CODETEAM_SESSION"}
    env["HOME"] = str(W / "home")
    return subprocess.run([LAND, str(W / "team.toml"), *args], capture_output=True, text=True, env=env)


REPO.mkdir()
(REPO / "A").mkdir()
(REPO / "A" / "a.txt").write_text("a\n")
subprocess.run(["git", "init", "-q", "-b", "main", str(REPO)], check=True)
subprocess.run([*G, "add", "-A"], check=True)
subprocess.run([*G, "commit", "-qm", "init"], check=True)
subprocess.run([*G, "branch", "integration"], check=True)
subprocess.run([*G, "branch", "landing"], check=True)
(W / "team.toml").write_text(f'''repo = "{REPO}"
integration = "integration"
worktree_root = "{ROOT}"
[[lanes]]
name = "A"
path = "A"
[land]
seed_index = false
codegraph = false
notify = "true"
owner_notify = "true"
''')

subprocess.run([*G, "branch", "wo/A/left", "integration"], check=True)            # what a dead cut leaves
r = land("wo-cut", "A", "left")
t("a leftover branch with nothing of its own is replaced and the cut goes on",
  r.returncode == 0 and (ROOT / "wo" / "A" / "left").is_dir(), r.stdout + r.stderr)
t("the old branch is kept under refs/archive/wo", subprocess.run([*G, "rev-parse", "-q", "--verify",
  "refs/archive/wo/left"], capture_output=True).returncode == 0)

subprocess.run([*G, "branch", "wo/A/own", "integration"], check=True)
subprocess.run([*G, "commit", "-q", "--allow-empty", "-m", "own work"], check=False)   # on main, not on the branch
subprocess.run(["git", "-C", str(REPO), "update-ref", "refs/heads/wo/A/own",
                subprocess.run([*G, "rev-parse", "main"], capture_output=True, text=True).stdout.strip()], check=True)
r = land("wo-cut", "A", "own")
t("a leftover branch with commits of its own is refused by name", r.returncode != 0 and "commits of its own" in r.stderr,
  r.stdout + r.stderr)
t("and it is left as it was", subprocess.run([*G, "rev-parse", "-q", "--verify", "refs/heads/wo/A/own"],
  capture_output=True).returncode == 0)

print(f"\n{'all passed' if not fails else f'{fails} failed'}  ({W})")
sys.exit(1 if fails else 0)
