#!/usr/bin/env -S python3 -u
"""The hook lets the landing tool move base to an adopted commit on landing; a queue entry that can no longer land does not stop the queue; a team's integration test
folders are not run at landing; the landing check asks for the unit group. A throwaway repo."""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HOME = Path(__file__).resolve().parents[2]
LAND = str(HOME / "bin" / "codeteam-land")
ld = importlib.machinery.SourceFileLoader("cl", LAND)
sp = importlib.util.spec_from_loader("cl", ld)
cl = importlib.util.module_from_spec(sp)
sys.modules["cl"] = cl
ld.exec_module(cl)
W = Path(tempfile.mkdtemp(prefix="land-unblock-"))
REPO, ROOT = W / "repo", W / "team"
fails = 0
G = "git -c user.email=t@t -c user.name=t"


def t(label, cond, detail=""):
    global fails
    print(("  PASS " if cond else "  FAIL ") + label + ("" if cond else f"  [{detail}]"))
    fails += not cond


def sh(cmd, cwd=REPO, check=True):
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"setup failed: {cmd}\n{r.stdout}{r.stderr}")
    return r


def land(*args, session="orc"):
    e = {k: v for k, v in os.environ.items() if not k.startswith("CODETEAM_")}
    # Keep home-scoped state inside the fixture, including logs from any stray land-check.
    e["HOME"] = str(W / "home")
    # That HOME has no .gitconfig, and git refuses even a conflicting merge without a committer identity.
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@t"), ("GIT_COMMITTER_NAME", "t"),
                 ("GIT_COMMITTER_EMAIL", "t@t")):
        e.setdefault(k, v)
    e["CODETEAM_SESSION"] = session
    return subprocess.run([LAND, str(W / "team.toml"), *args], capture_output=True, text=True, env=e)


(REPO / "A" / "tests").mkdir(parents=True)
(REPO / "A" / "x").write_text("1\n")
(REPO / "A" / "tests" / "t").write_text("1\n")
sh(f"git init -q -b main && git add -A && {G} commit -qm init && git branch integration")
# integration holds a commit made before the hook (adopted at the move), then the hook goes in
sh(f"git checkout -q integration && echo 2 > A/x && {G} commit -qam 'adopted, no trailer' && git checkout -q main")
(W / "team.toml").write_text(f'''repo = "{REPO}"
integration = "integration"
worktree_root = "{ROOT}"
[[lanes]]
name = "A"
path = "A"
owns = ["A/tests/live"]
[land]
check = ""
gates = ""
test = "true"
skip_tests = ["A/tests/*"]
notify = "echo {{kind}} {{to}} {{text}} >> {W / 'notify.log'}"
owner_notify = "true"
''')
sh("git branch landing integration")
land("install-hook")

print("== the hook and the base branch")
tip = sh("git rev-parse integration").stdout.strip()
r = sh(f"CODETEAM_LAND_TOOL=1 git update-ref refs/heads/main {tip}", check=False)
t("the tool moves base to a commit on landing, past an adopted commit", r.returncode == 0, r.stderr)
sh(f"git checkout -q --detach && echo 9 > A/x && {G} commit -qam 'not on landing'")
other = sh("git rev-parse HEAD").stdout.strip()
r = sh(f"git update-ref refs/heads/main {other}", check=False)
t("the base branch still refuses a commit that is not on landing", r.returncode != 0 and "only codeteam-land" in r.stderr, r.stderr)
r = sh(f"git update-ref refs/heads/integration {other}", check=False)
t("integration still refuses a commit that is not a landing", r.returncode != 0, r.stderr)
sh("git checkout -q main")

print("== a queue entry that can no longer land")
q = ROOT / "land" / "queue"
(ROOT / "land" / "wo" / "gone.landed.json").write_text(json.dumps({"wo": "gone", "zone": "A", "tree": str(W / "x")}))
(q / "0-1-gone.json").write_text(json.dumps({"wos": ["gone"], "queued": "2026-11-09T18:50:00-06:00", "state": "waiting"}))
(q / "0-2-ghost.json").write_text(json.dumps({"wos": ["ghost"], "queued": "2026-11-09T18:50:00-06:00", "state": "waiting"}))
r = land("queue-run", "--once")
t("queue-run does not die on them", r.returncode == 0, r.stdout + r.stderr)
t("the entry of a landed work order is removed", not (q / "0-1-gone.json").exists())
t("the entry of an unknown work order is set aside", (ROOT / "land" / "queue-stale" / "0-2-ghost.json").exists())
time.sleep(1)
t("and the orchestrator is told", "no record (ghost)" in (W / "notify.log").read_text())
r = land("land-next", "gone")
t("land-next refuses a landed work order", r.returncode != 0 and "has landed" in r.stderr, r.stderr)

print("== what the landing check runs")
team = cl.Team(str(W / "team.toml"))
(REPO / "A" / "tests" / "live").mkdir()
steps = cl.zone_tests(team, str(REPO), "A", "land")
t("a folder in skip_tests is not a landing step; the zone's own folder is", [n for n, _ in steps] == ["tests A (A)"], steps)
t("the landing check asks for the unit group", cl.team_env(team).get("GROUP") == "unit")
print(f"\n{'all passed' if not fails else f'{fails} failed'}  ({W})")
sys.exit(1 if fails else 0)
