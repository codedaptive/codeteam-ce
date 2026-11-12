#!/usr/bin/env -S python3 -u
"""Stage 6 validation in a second local clone: reviewed targets, fix-forward findings, the toolchain check,
and the interface rule's declaration test. Nothing outside a temp folder is touched."""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
LAND = str(HERE / "bin" / "codeteam-land")
W = Path(tempfile.mkdtemp(prefix="land-alpha-"))
REPO, ALPHA = W / "repo", W / "alpha"
LAND_DIR = W / "team" / "land"
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
    e = {k: v for k, v in os.environ.items() if k != "CODETEAM_SESSION"}
    # land-check writes its log under HOME, including when the tier is local.
    e["HOME"] = str(W / "home")
    # That HOME has no .gitconfig, and git refuses even a conflicting merge without a committer identity.
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@t"), ("GIT_COMMITTER_NAME", "t"),
                 ("GIT_COMMITTER_EMAIL", "t@t")):
        e.setdefault(k, v)
    e.update(env or {})
    return subprocess.run([LAND, str(W / "team.toml"), *args], capture_output=True, text=True, env=e)


def wo(zone, name, path, text, *flags):
    tree = Path(land("wo-cut", zone, name).stdout.strip())
    (tree / path).write_text(text + "\n")
    sh(f"git add -A && git -c user.email=t@t -c user.name=l commit -qm {name}", cwd=tree)
    r = land("land", name, *flags)
    assert r.returncode == 0, r.stdout + r.stderr
    r = land("reviewed", name, env={"CODETEAM_SESSION": "Kong"})
    assert r.returncode == 0, r.stdout + r.stderr
    r = land("queue-run", "--once")
    assert r.returncode == 0, r.stdout + r.stderr
    r = land("recheck-run", "--once")
    assert r.returncode == 0, r.stdout + r.stderr


def results():
    p = LAND_DIR / "validation-results.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def wait_for(cond, secs=30):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


def integ(path):
    return sh(f"git show landing:{path}").stdout.strip()


def notes():
    p = W / "notify.log"
    return p.read_text() if p.exists() else ""


REPO.mkdir()
(REPO / "A").mkdir()
(REPO / "A" / "Cargo.toml").write_text('[package]\nname = "a"\n')
(REPO / "A" / "value").write_text("1\n")
(REPO / "A" / "limit").write_text("50\n")
sh("git init -q -b main && git add -A && git -c user.email=t@t -c user.name=t commit -qm init && git branch integration && git branch landing")
sh(f"git clone -q {REPO} {ALPHA}", cwd=W)
MANIFEST = f'''repo = "{REPO}"
integration = "integration"
worktree_root = "{W / 'team'}"
[[lanes]]
name = "A"
path = "A"
[land]
check = ""
test = "true"
gates = ""
seed_index = false
interface = false
notify = "echo {{kind}} {{to}} {{text}} >> {W / 'notify.log'}"
owner_notify = "echo OWNER {{title}} {{body}} >> {W / 'notify.log'}"
[land.remote]
local = true
host = "local"
path = "{ALPHA}"
suite = "test $(cat A/value) -lt $(cat A/limit)"
toolchain = ["echo tc-$LAND_TC"]
'''
(W / "team.toml").write_text(MANIFEST)
os.environ["LAND_TC"] = "same"
land("install-hook")
t("alpha-install puts land-check in the clone", land("alpha-install").returncode == 0 and
  (ALPHA / ".git" / "land-check").exists())

print("== reviewed commits validate once")
wo("A", "g1", "A/value", "2")
t("landing alone does not start validation", results() == [] and not (LAND_DIR / "alpha-latest").exists())
r = land("validate-run", "--once")
t("Stage 6 runs the suite in the clone", r.returncode == 0 and len(results()) == 1 and
  results()[0]["result"] == "pass" and results()[0]["tests"][0]["name"] == "suite", r.stdout + r.stderr)
land("validate-run", "--once")
t("the last validated commit is not repeated", len(results()) == 1)
t("Stage 6 writes no migrate results", not (LAND_DIR / "results.jsonl").exists())

print("== red: nothing is undone; one fix-forward finding")
wo("A", "r1", "A/value", "4")
land("validate-run", "--once")
wo("A", "bad", "A/value", "60")
land("validate-run", "--once")
t("a failing validation suite records a per-test failure", len(results()) == 3 and
  results()[-1]["result"] == "fail" and results()[-1]["tests"][0]["result"] == "fail", results())
t("nothing is reverted: the failing landing stays on landing", integ("A/value") == "60" and
  "revert-bad" not in land("queue").stdout)
t("the orchestrator receives the finding and its fix landing command", wait_for(
  lambda: "FIX-FORWARD validation#1" in notes() and "--fixes validation#1" in notes()), notes()[-600:])
wo("A", "still", "A/extra", "continued work")
land("validate-run", "--once")
t("Stage 6 runs while a fix is open", len(results()) == 4 and results()[-1]["result"] == "fail", results())
open_items = json.loads((LAND_DIR / "findings" / "validation.json").read_text())
t("an already-failing test adds C to its open fix, no new finding", len(open_items) == 1 and
  open_items[0]["id"] == "validation#1" and open_items[0]["state"] == "open" and
  len(open_items[0]["commits"]) == 2 and open_items[0]["commits"][-1] == results()[-1]["commit"], open_items)

wo("A", "fix", "A/limit", "100", "--fixes", "validation#1")
(REPO / "notes.txt").write_text("a designer's uncommitted note\n")
r = land("validate-run", "--once")
t("a fix validates without touching unrelated base edits", r.returncode == 0 and results()[-1]["result"] == "pass"
  and (REPO / "notes.txt").read_text() == "a designer's uncommitted note\n", r.stdout + r.stderr)
items = json.loads((LAND_DIR / "findings" / "validation.json").read_text())
t("landing with --fixes closes the validation finding", items[0]["state"] == "closed" and items[0]["fixed_by"] == "fix", items)

loader = importlib.machinery.SourceFileLoader("cl", LAND)
spec = importlib.util.spec_from_loader("cl", loader)
cl = importlib.util.module_from_spec(spec)
loader.exec_module(cl)
team = cl.Team(str(W / "team.toml"))
sent = []
team.notify = lambda to, kind, text: sent.append(text)
tip = sh("git rev-parse integration").stdout.strip()
failed = [{"name": "suite", "result": "fail", "seconds": 1}]
cl.apply_validation_findings(team, tip, failed, "t1")
cl.apply_validation_findings(team, tip, failed, "t2")
t("the same failure is requested once", len(sent) == 1, sent)
cl.apply_validation_findings(team, tip, [{"name": "suite", "result": "pass", "seconds": 1}], "t3")
cl.apply_validation_findings(team, tip, failed, "t4")
t("a failure after a pass gets a new request", len(sent) == 2, sent)
cl.apply_validation_findings(team, tip, [{"name": "suite", "result": "pass", "seconds": 1}], "t5")
t("a failure with no named test still produces a suite finding", cl.validation_tests(
  {"result": "fail", "seconds": 1, "tail": "nothing recognisable"}, None, []) == failed)

print("== toolchain")
wo("A", "tc", "A/value", "5")
(W / "team.toml").write_text(MANIFEST.replace("[land.remote]\n", '[land.remote]\nremote_env = { LAND_TC = "other" }\n'))
land("validate-run", "--once")
last = results()[-1]
t("a toolchain mismatch refuses the run and says why", last.get("result") == "toolchain" and
  "toolchain differs" in last.get("detail", ""), last)
t("the orchestrator and the owner are told it was not run", wait_for(lambda: "could not run on" in notes() and "OWNER" in notes()))
(W / "team.toml").write_text(MANIFEST)

print("== interface rule (A1)")
src = ["pub fn open(path: &str,", "           timeout: u32) -> Store {", "    let x = 1;", "    x", "}"]
seed = {"path": "s.rs", "span": "L1-L5", "kind": "function", "name": "open"}
t("a changed signature line is a declaration change", cl.declaration_changed(seed, {"s.rs": {2}}, lambda p: src))
t("a body-only edit is not", not cl.declaration_changed(seed, {"s.rs": {3}}, lambda p: src))
blast_changed = [{"path": "s.rs", "hunks": [{"lines": [{"n": 2, "sign": "+"}, {"n": None, "sign": "-"}]}]}]
t("blast's changed hunks give the new-side lines", cl.plus_lines(blast_changed) == {"s.rs": {2}})

print(f"\n{'all passed' if not fails else f'{fails} failed'}  ({W})")
sys.exit(1 if fails else 0)
