#!/usr/bin/env -S python3 -u
"""test-flow for codeteam-land (branch flow v5, phase 1). A throwaway repo with three zones, C depends on B, B on A
(Cargo path dependencies, which is what the reach closure follows). Nothing outside a temp folder is touched."""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

LAND = str(Path(__file__).resolve().parents[2] / "bin" / "codeteam-land")
W = Path(tempfile.mkdtemp(prefix="land-flow-"))
REPO = W / "repo"
fails = 0


def sh(cmd, cwd=REPO, env=None, check=True):
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, env=env)
    if check and r.returncode:
        raise SystemExit(f"setup failed: {cmd}\n{r.stdout}{r.stderr}")
    return r


def t(label, cond, detail=""):
    global fails
    print(("  PASS " if cond else "  FAIL ") + label + ("" if cond else f"  [{detail}]"))
    fails += not cond


def land(*args, env=None):
    e = dict(os.environ)
    # Keep child processes' home-scoped logs and state inside the fixture.
    e["HOME"] = str(W / "home")
    # That HOME has no .gitconfig, and git refuses even a conflicting merge without a committer identity.
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@t"), ("GIT_COMMITTER_NAME", "t"),
                 ("GIT_COMMITTER_EMAIL", "t@t")):
        e.setdefault(k, v)
    e.update(env or {})
    e.pop("CODETEAM_SESSION", None) if not (env and "CODETEAM_SESSION" in env) else None
    result = subprocess.run([LAND, str(W / "team.toml"), *args], capture_output=True, text=True, env=e)
    if args[0] == "land" and result.returncode == 0:
        entry = next(json.loads(p.read_text()) for p in (W / "team" / "land" / "queue").glob("*.json")
                     if args[1] in json.loads(p.read_text())["wos"])
        for wo in entry["wos"]:
            row = json.loads((W / "team" / "land" / "reviews" / f"{wo}.json").read_text())
            for reviewer in row["reviewers"]:
                verdict = subprocess.run([LAND, str(W / "team.toml"), "reviewed", wo], capture_output=True, text=True,
                                         env=dict(e, CODETEAM_SESSION=reviewer))
                assert verdict.returncode == 0, verdict.stdout + verdict.stderr
    if args[0] in ("queue-run", "land-one") and result.returncode == 0:
        tip = sh("git rev-parse landing").stdout.strip()
        with (W / "team" / "land" / "validation-results.jsonl").open("a") as file:
            file.write(json.dumps({"commit": tip, "result": "pass", "tests": []}) + "\n")
        promoted = subprocess.run([LAND, str(W / "team.toml"), "promote", tip], capture_output=True, text=True, env=e)
        assert promoted.returncode == 0, promoted.stdout + promoted.stderr
    return result


def gate_runs():
    p = W / "gate.log"
    return p.read_text().splitlines() if p.exists() else []


def integ(path):
    return sh(f"git show integration:{path}").stdout.strip()


def edit(wo, path, text, msg=None):
    tree = Path(json.loads((W / "team" / "land" / "wo" / f"{wo}.json").read_text())["tree"])
    (tree / path).parent.mkdir(parents=True, exist_ok=True)
    (tree / path).write_text(text + "\n")
    sh(f"git add -A && git -c user.email=t@t -c user.name=lead commit -qm {msg or wo}", cwd=tree)
    return tree


def cut(zone, wo):
    r = land("wo-cut", zone, wo)
    assert r.returncode == 0, r.stderr
    return Path(r.stdout.strip())


# ---- the repo
REPO.mkdir()
for z, dep in (("A", None), ("B", "A"), ("C", "B")):
    (REPO / z).mkdir()
    (REPO / z / "Cargo.toml").write_text(f'[package]\nname = "{z.lower()}"\n' +
                                         (f'[dependencies]\n{dep.lower()} = {{ path = "../{dep}" }}\n' if dep else ""))
    (REPO / z / "value").write_text("1\n")
(REPO / "C" / "notes").write_text("1\n2\n3\n4\n5\n")
(REPO / "type-check.sh").write_text("! grep -rq SYNTAX A B C\n")
# a zone's test: its own value is a number, and every value it depends on is below 100
(REPO / "run-tests.sh").write_text(
    'echo "$1 $CODETEAM_TEST_GROUP" >> "$GATE_LOG"\n'
    'case "$1" in A) deps="A";; B) deps="A B";; C) deps="A B C";; esac\n'
    'for d in $deps; do v=$(cat $d/value); case "$v" in *[!0-9]*|"") exit 1;; esac; [ "$v" -lt 100 ] || exit 1; done\n')
sh("git init -q -b main && git add -A && git -c user.email=t@t -c user.name=t commit -qm init && git branch integration && git branch landing")
(W / "team.toml").write_text(f'''repo = "{REPO}"
integration = "integration"
worktree_root = "{W / 'team'}"
guard = "Kong"
[[lanes]]
name = "A"
path = "A"
[[lanes]]
name = "B"
path = "B"
[[lanes]]
name = "C"
path = "C"
[env]
CODETEAM_OWNS = ""
[land]
check = "sh type-check.sh"
test = "sh run-tests.sh {{zone}}"
gates = ""
seed_index = false
interface = false
notify = "echo {{kind}} {{to}} {{text}} >> {W / 'notify.log'}"
''')
os.environ["GATE_LOG"] = str(W / "gate.log")
os.environ.pop("CODETEAM_SESSION", None)
r = land("install-hook")
assert r.returncode == 0, r.stderr

print("== landing")
cut("A", "a1"); edit("a1", "A/value", "2")
cut("C", "c1"); edit("c1", "C/value", "3")
before = len(gate_runs())
r = land("land", "a1")
t("land checks A's units and A and its direct dependent B's integration tests before queueing",
  r.returncode == 0 and sorted(gate_runs()[before:]) == ["A integration", "A unit", "B integration"], r.stdout + r.stderr)
before = len(gate_runs())
r = land("land", "c1")
t("land checks C's units and integration tests only", r.returncode == 0 and
  gate_runs()[before:] == ["C unit", "C integration"], r.stdout + r.stderr)
cut("B", "b-open")                 # B has a work order open, so it is told; a zone with none is not
before = len(gate_runs())
land("queue-run", "--once")
t("one pass lands the oldest entry only", integ("A/value") == "2" and integ("C/value") == "1", land("queue").stdout)
t("the landing runner runs no tests", gate_runs()[before:] == [], gate_runs()[before:])
land("queue-run", "--once")
t("the next pass lands C without repeating its tests", integ("C/value") == "3" and gate_runs()[before:] == [], gate_runs()[before:])
log = [json.loads(l) for l in (W / "team" / "land" / "landed.log").read_text().splitlines()]
t("one landing merge commit per work order, in order", [r["wos"] for r in log if r.get("hash")] == [["a1"], ["c1"]] and
  sh("git log --first-parent --format=%s integration -2").stdout.split("\n")[:2] == ["c1 (C)", "a1 (A)"])
t("each commit carries the trailer", "Landed-By: codeteam land-one" in sh("git log -1 --format=%B integration").stdout)
t("the work order tree is deleted; history kept under refs/landed", not (W / "team" / "wo" / "A" / "a1").exists() and
  sh("git rev-parse -q --verify refs/landed/a1", check=False).returncode == 0)
t("zones reached with open work orders were told at promotion", "Coord-B" in (W / "notify.log").read_text())

print("== reach")
cut("C", "c2"); edit("c2", "C/value", "4")
before = len(gate_runs()); land("land", "c2"); land("queue-run", "--once")
t("a change in C runs C only", gate_runs()[before:] == ["C unit", "C integration"], gate_runs()[before:])

print("== the integration check")
loader = importlib.machinery.SourceFileLoader("cl", LAND)
spec = importlib.util.spec_from_loader("cl", loader)
cl = importlib.util.module_from_spec(spec)
loader.exec_module(cl)
def unit_record(tree, folder):
    # This throwaway repo has no Makefile: zone.mk includes the empty owns term in each folder's unit key.
    git_dir = Path(sh("git rev-parse --path-format=absolute --git-dir", cwd=tree).stdout.strip())
    commit = sh("git rev-parse HEAD", cwd=tree).stdout.strip()
    row = {"commit": commit, "clean": True, "group": "unit", "key": f"one {folder} owns=",
           "result": "PASS", "exit": 0, "time": "2026-11-10T00:00:00+00:00", "record": "x.json"}
    with (git_dir / "zone-test-commits.jsonl").open("a") as f:
        f.write(json.dumps(row) + "\n")


cut("A", "bad"); tree = edit("bad", "A/value", "200")
unit_record(tree, "A")
before = len(gate_runs())
r = land("land", "bad")
t("a work order that breaks integration tests does not queue (exit 3)", r.returncode == 3 and
  integ("A/value") == "2" and "bad" not in land("queue").stdout, r.stdout + r.stderr)
t("a lead's current PASS record satisfies only the unit step", sorted(gate_runs()[before:]) == ["A integration", "B integration"],
  gate_runs()[before:])
t("--untested is refused", land("land", "bad", "--untested").returncode == 5)
cut("B", "syn"); tree = edit("syn", "B/value", "SYNTAX"); unit_record(tree, "B")
r = land("land", "syn")
t("the whole-repo type check fails before queueing", r.returncode == 3 and "FAIL type check" in r.stdout and
  "syn" not in land("queue").stdout, r.stdout + r.stderr)

print("== entries are checked separately")
submissions = {}
for wo, z, v in (("b1", "B", "5"), ("b2", "A", "300"), ("b3", "C", "6")):
    cut(z, wo); edit(wo, f"{z}/value", v); submissions[wo] = land("land", wo)
land("queue-run", "--once")
land("queue-run", "--once")
land("queue-run", "--once")
t("separate passes with a broken middle entry land the other two in order", integ("B/value") == "5" and integ("C/value") == "6"
  and integ("A/value") == "2", (integ("A/value"), integ("B/value"), integ("C/value")))
t("the broken one fails its unit check and stays unqueued", submissions["b2"].returncode == 3 and
  "FAIL tests A" in submissions["b2"].stdout and "b2" not in land("queue").stdout, submissions["b2"].stdout)

print("== conflicts")
cut("A", "x1"); cut("A", "x2")
edit("x1", "A/value", "7"); edit("x2", "A/value", "8")
land("land", "x1"); land("queue-run", "--once")
r = land("land", "x2")
t("a conflict with landed work goes back at land (exit 2), files named", r.returncode == 2 and "A/value" in r.stdout, r.stdout)
tree = Path(json.loads((W / "team" / "land" / "wo" / "x2.json").read_text())["tree"])
(tree / "A" / "value").write_text("8\n"); sh("git add -A && git -c user.email=t@t -c user.name=l commit -qm fix", cwd=tree)
land("land", "x2"); land("queue-run", "--once")
t("after the lead resolves it, it lands", integ("A/value") == "8")
cut("C", "s1"); cut("C", "s3"); cut("A", "s2")
edit("s1", "C/notes", "one-changed\n2\n3\n4\n5"); edit("s3", "C/notes", "1\n2\n3\n4\nfive-changed")
edit("s2", "A/value", "11")
land("land", "s3"); land("land", "s2")
land("land", "s1"); land("land-next", "s1")
r = land("land-one", "s1")
land("queue-run", "--once")
land("queue-run", "--once")
t("an independent entry lands after integration moves", integ("A/value") == "11")
t("nonconflicting edits to the same file merge", integ("C/notes").splitlines() == ["one-changed", "2", "3", "4", "five-changed"])

print("== land-one, --with, hook, revert")
cut("B", "d1"); edit("d1", "B/value", "14"); land("land", "d1")
r = land("land-one", "d1")
t("land-one lands the reviewed tip and records review before", r.returncode == 0 and integ("B/value") == "14" and
  [json.loads(line) for line in (W / "team" / "land" / "landed.log").read_text().splitlines() if json.loads(line).get("hash")][-1]["review"] == "before", r.stderr)
cut("A", "w1"); cut("B", "w2"); edit("w1", "A/value", "15"); edit("w2", "B/value", "13")
r = land("land", "w1", "--with", "w2")
queued = [json.loads(p.read_text()) for p in (W / "team" / "land" / "queue").glob("*.json")]
t("--with queues both work orders as one entry", r.returncode == 0 and len(queued) == 1 and
  queued[0]["wos"] == ["w1", "w2"], r.stdout + r.stderr)
if queued:
    land("land-cancel", "w1")
cut("A", "w3"); cut("B", "w4"); edit("w3", "A/value", "16"); edit("w4", "B/value", "17")
land("land", "w3"); land("land", "w4"); land("queue-run", "--once"); land("queue-run", "--once")
t("independent checked entries both land", integ("A/value") == "16" and integ("B/value") == "17")
r = sh("git update-ref refs/heads/integration main^", check=False)
t("a direct move of integration is refused by the hook", r.returncode != 0 and integ("A/value") == "16", r.stderr)
r = sh("git branch -f integration main^", check=False)
t("so is git branch -f", r.returncode != 0 and integ("A/value") == "16")
t("base (main) is guarded too: a direct commit on it is refused", sh("git -c user.email=t@t -c user.name=t commit -q --allow-empty -m direct",
                                                                    check=False).returncode != 0)
t("an ordinary commit in a work order tree is not refused",
  sh("git -c user.email=t@t -c user.name=t commit -q --allow-empty -m x", cwd=cut("C", "plain"), check=False).returncode == 0)
r = land("revert", "w4"); land("queue-run", "--once")
t("revert lands as a landing of its own and restores the value", integ("B/value") == "14" and integ("A/value") == "16",
  (r.stdout, r.stderr, integ("B/value")))
cut("C", "h1"); cut("C", "h2"); edit("h1", "C/value", "20"); edit("h2", "C/doc", "x")
land("land", "h1"); land("land", "h2"); land("land-next", "h2"); land("land-hold", "h1")
q = land("queue").stdout.splitlines()
t("land-next puts it first; land-hold parks it", q and "h2" in q[0] and "HELD" in q[1], q)

print(f"\n{'all passed' if not fails else f'{fails} failed'}  ({W})")
sys.exit(1 if fails else 0)
