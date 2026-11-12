#!/usr/bin/env -S python3 -u
"""codeteam-land migrate on a throwaway copy of the v2 layout: exchange ahead of integration, lanes that pushed
(squash onto exchange, exchange merged back) and one with unpushed work, a request worktree, the exchange and
integration worktrees. Nothing outside a temp folder is touched."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

LAND = str(Path(__file__).resolve().parents[2] / "bin" / "codeteam-land")
W = Path(tempfile.mkdtemp(prefix="land-migrate-"))
REPO, ROOT, ALPHA = W / "repo", W / "team", W / "alpha"
fails = 0


def sh(cmd, cwd=REPO, check=True):
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"setup failed: {cmd}\n{r.stdout}{r.stderr}")
    return r


def t(label, cond, detail=""):
    global fails
    print(("  PASS " if cond else "  FAIL ") + label + ("" if cond else f"  [{detail}]"))
    fails += not cond


def land(*args, env=None):
    e = dict(os.environ)
    # Migrate's validation tier keeps its land-check log under HOME; keep it inside the fixture.
    e["HOME"] = str(W / "home")
    # That HOME has no .gitconfig, and git refuses even a conflicting merge without a committer identity.
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@t"), ("GIT_COMMITTER_NAME", "t"),
                 ("GIT_COMMITTER_EMAIL", "t@t")):
        e.setdefault(k, v)
    e.update(env or {})
    return subprocess.run([LAND, str(W / "team.toml"), *args], capture_output=True, text=True, env=e)


C = "git -c user.email=t@t -c user.name=t commit -qam"
REPO.mkdir()
for z in ("A", "B"):
    (REPO / z).mkdir()
    (REPO / z / "value").write_text("1\n")
sh("git init -q -b main && git add -A && git -c user.email=t@t -c user.name=t commit -qm init")
sh("git branch integration && git branch exchange && git branch lane/A exchange && git branch lane/B exchange")
for name, branch in (("exchange/repo-integration-exchange", "exchange"), ("integration/repo-main-integration", "integration"),
                     ("workcrews/A/repo-exchange-A", "lane/A"), ("workcrews/B/repo-exchange-B", "lane/B")):
    sh(f"git worktree add -q {ROOT / name} {branch}")
LA, LB, EX = ROOT / "workcrews/A/repo-exchange-A", ROOT / "workcrews/B/repo-exchange-B", ROOT / "exchange/repo-integration-exchange"
# lane A: work, pushed v2-style (squash onto exchange, exchange merged back)
(LA / "A" / "value").write_text("2\n"); sh(f"{C} a-work", cwd=LA)
sh("git merge --squash -q lane/A && git -c user.email=t@t -c user.name=t commit -qm 'squash a'", cwd=EX)
sh("git merge -q --no-edit exchange", cwd=LA)
# lane B: pushed once, then more work not pushed
(LB / "B" / "value").write_text("2\n"); sh(f"{C} b-work", cwd=LB)
sh("git merge --squash -q lane/B && git -c user.email=t@t -c user.name=t commit -qm 'squash b'", cwd=EX)
sh("git merge -q --no-edit exchange", cwd=LB)
(LB / "B" / "notes").write_text("unpushed\n"); sh("git add -A && git -c user.email=t@t -c user.name=t commit -qm b-more", cwd=LB)
# a request worktree in lane A
RQ = ROOT / "workcrews/A/requests/agent-1"
sh(f"git worktree add -q -b worktree-agent-1 {RQ} lane/A")
(RQ / "A" / "value").write_text("3\n"); sh(f"{C} req", cwd=RQ)
IW = ROOT / "integration/repo-main-integration"
(IW / "CHANGELOG").write_text("only on integration\n")
sh("git add -A && git -c user.email=t@t -c user.name=t commit -qm 'changelog on integration'", cwd=IW)
# an unfinished item that reached exchange and was taken off it before the move
(EX / "A" / "extra").write_text("unfinished\n"); sh("git add -A && git -c user.email=t@t -c user.name=t commit -qm 'unfinished thing'", cwd=EX)
UNF = sh("git rev-parse HEAD", cwd=EX).stdout.strip()
sh(f"git -c user.email=t@t -c user.name=t revert --no-edit {UNF} && git -c user.email=t@t -c user.name=t commit -q --amend -m 'revert(A): take {UNF[:10]} off exchange before the v5 move'", cwd=EX)
sh(f"git clone -q {REPO} {ALPHA}", cwd=W)
(W / "team.toml").write_text(f'''repo = "{REPO}"
integration = "integration"
exchange = "exchange"
lane_branch_prefix = "lane/"
worktree_root = "{ROOT}"
[[lanes]]
name = "A"
path = "A"
[[lanes]]
name = "B"
path = "B"
[land]
check = ""
test = "true"
gates = ""
seed_index = false
interface = false
notify = "echo {{kind}} {{to}} {{text}} >> {W / 'notify.log'}"
owner_notify = "true"
[land.remote]
local = true
host = "local"
path = "{ALPHA}"
suite = "true"
toolchain = ["echo same"]
''')
land("install-hook"); land("alpha-install")

print("== plan")
r = land("migrate", "plan")
t("plan lists only lane B as having unpushed work", "B: 1 file(s)" in r.stdout and "A: " not in r.stdout.split("unpushed")[1].split("request")[0], r.stdout)
t("plan counts the request worktree and what step 6 retires", "registered as work orders in progress): 1" in r.stdout and
  "2 standing lane worktrees, 1 exchange, 1 integration" in r.stdout, r.stdout)

print("== adopt")
land("migrate", "check")
r = land("migrate", "adopt")
t("adopt refuses when integration has a commit exchange lacks, and names it", r.returncode == 5 and
  "changelog on integration" in r.stderr, r.stderr)
sh("git -c user.email=t@t -c user.name=t cherry-pick integration", cwd=EX)
t("adopt refuses before exchange's tip has passed the validation tier", land("migrate", "adopt").returncode == 5)
t("--force-unchecked is refused outside the dry run", land("migrate", "adopt", "--force-unchecked").returncode == 5)
t("check runs the validation tier on exchange's tip", land("migrate", "check").returncode == 0)
(EX / "notes.md").write_text("a docs-only commit after the passing run\n")   # the gate's rule: docs only, no suite
sh("git add -A && git -c user.email=t@t -c user.name=t commit -qm 'notes after the check'", cwd=EX)
t("adopt refuses while integration is checked out", land("migrate", "adopt").returncode == 5)
t("retire --only integration removes that worktree", land("migrate", "retire", "--only", "integration").returncode == 0 and
  not (ROOT / "integration/repo-main-integration").exists())
r = land("migrate", "adopt")
t("adopt moves integration to exchange's tip through the hook (docs only since its passing run; a\n"
  "  non-docs commit since the run was refused above)", r.returncode == 0 and
  sh("git rev-parse integration").stdout == sh("git rev-parse exchange").stdout, r.stderr)
t("the hook still refuses any other move", sh("git update-ref refs/heads/integration main", check=False).returncode != 0)

print("== lanes, requests, retire")
r = land("migrate", "lanes")
wo_b = ROOT / "land" / "wo" / "v2-B.json"
t("lane B's unpushed work becomes a work order tree; lane A gets none", r.returncode == 0 and wo_b.exists() and
  not (ROOT / "land" / "wo" / "v2-A.json").exists(), r.stdout + r.stderr)
tree_b = Path(json.loads(wo_b.read_text())["tree"])
t("that tree holds exactly the unpushed change on top of integration",
  sh("git diff --name-only integration HEAD", cwd=tree_b).stdout.split() == ["B/notes"])
r = land("migrate", "reverts")
rl = ROOT / "land" / "wo" / f"v2-reland-A-{UNF[:8]}.json"
t("reverts brings each item taken off exchange back as a work order in progress, unlanded", r.returncode == 0 and
  rl.exists() and (Path(json.loads(rl.read_text())["tree"]) / "A" / "extra").exists() and
  sh("git show integration:A/extra", check=False).returncode != 0, r.stdout + r.stderr)
t("its zone is told", "unfinished as it was" in (W / "notify.log").read_text())
t("requests registers the request worktree as a work order", "registered 1" in land("migrate", "requests").stdout)
t("the request pulls from integration cleanly (wo-pull)", land("wo-pull", "agent-1").returncode == 0)
(LB / "B" / "value").write_text("stashed\n"); sh("git -c user.email=t@t -c user.name=t stash -q", cwd=LB)
t("plan counts the stashes", "stashes kept as archived branches at retire: 1" in land("migrate", "plan").stdout)
r = land("migrate", "retire")
t("retire keeps every stash as an archived ref first", sh("git rev-parse -q --verify refs/archive/v2/stash/0", check=False).returncode == 0, r.stdout)
t("retire removes the lane and exchange worktrees and archives their branches", r.returncode == 0 and
  not LA.exists() and not EX.exists() and sh("git rev-parse -q --verify refs/archive/v2/lane/B", check=False).returncode == 0)
r = land("migrate-v54")
assert r.returncode == 0, r.stdout + r.stderr
r = land("land", "v2-B")
assert r.returncode == 0, r.stdout + r.stderr
r = land("reviewed", "v2-B", env={"CODETEAM_SESSION": "Kong"})
assert r.returncode == 0, r.stdout + r.stderr
r = land("queue-run", "--once")
assert r.returncode == 0, r.stdout + r.stderr
t("the migrated work order lands like any other", sh("git show landing:B/notes", check=False).stdout.strip() == "unpushed")

print(f"\n{'all passed' if not fails else f'{fails} failed'}  ({W})")
sys.exit(1 if fails else 0)
