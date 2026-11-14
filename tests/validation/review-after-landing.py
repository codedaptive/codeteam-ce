#!/usr/bin/env -S python3 -u
"""Review before landing; Nagatha writes feature tests after landing;
findings name work orders and come back as fix-forward requests. A
throwaway repo, a stand-in codegraph."""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

LAND = str(Path(__file__).resolve().parents[2] / "bin" / "codeteam-land")
W = Path(tempfile.mkdtemp(prefix="review-after-"))
REPO, ROOT, BIN = W / "repo", W / "team", W / "bin"
fails = 0


def t(label, cond, detail=""):
    global fails
    print(("  PASS " if cond else "  FAIL ") + label + ("" if cond else f"  [{detail}]"))
    fails += not cond


def sh(cmd, cwd=REPO):
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"setup failed: {cmd}\n{r.stdout}{r.stderr}")
    return r


BIN.mkdir()
(BIN / "codegraph").write_text('#!/bin/sh\nif [ -f "$CG_MODE" ] && [ "$(cat "$CG_MODE")" = broken ]; then echo "no index"; exit 1; fi\n'
                               'case "$1" in blast) echo \'{"changed": [], "seeds": []}\';; *) echo \'[]\';; esac\n')
(BIN / "codegraph").chmod(0o755)
MODE = W / "cg-mode"


def land(*args, session="orc"):
    e = {k: v for k, v in os.environ.items() if not k.startswith("CODETEAM_")}
    # Keep home-scoped state inside the fixture, including logs from any stray land-check.
    e["HOME"] = str(W / "home")
    # That HOME has no .gitconfig, and git refuses even a conflicting merge without a committer identity.
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@t"), ("GIT_COMMITTER_NAME", "t"),
                 ("GIT_COMMITTER_EMAIL", "t@t")):
        e.setdefault(k, v)
    e.update(CODETEAM_SESSION=session, PATH=f"{BIN}:{os.environ['PATH']}", CG_MODE=str(MODE), CODETEAM_CODEGRAPH=str(BIN / "codegraph"))
    return subprocess.run([LAND, str(W / "team.toml"), *args], capture_output=True, text=True, env=e)


def wo(name, path, text="x\n", tag=()):
    tree = Path(land("wo-cut", "A", name).stdout.strip())
    (tree / path).parent.mkdir(parents=True, exist_ok=True)
    (tree / path).write_text(text)
    sh("git add -A && git -c user.email=t@t -c user.name=l commit -qm " + name, cwd=tree)
    return land("land", name, *tag)


def notes():
    time.sleep(0.5)
    f = W / "notify.log"
    return f.read_text() if f.exists() else ""


def landed(name):
    return (ROOT / "land" / "wo" / f"{name}.landed.json").exists()


def run():
    for p in (ROOT / "land" / "queue").glob("*.json"):
        for wo in json.loads(p.read_text())["wos"]:
            row = json.loads((ROOT / "land" / "reviews" / f"{wo}.json").read_text())
            for reviewer, state in row["reviewers"].items():
                if state == "pending":
                    result = land("reviewed", wo, session=reviewer)
                    assert result.returncode == 0, result.stdout + result.stderr
    result = land("queue-run", "--once")
    assert result.returncode == 0, result.stdout + result.stderr
    tip = sh("git rev-parse landing").stdout.strip()
    with (ROOT / "land" / "validation-results.jsonl").open("a") as file:
        file.write(json.dumps({"commit": tip, "result": "pass", "tests": []}) + "\n")
    result = land("promote", tip)
    assert result.returncode == 0, result.stdout + result.stderr


REPO.mkdir()
(REPO / "A").mkdir()
(REPO / "A" / "v.py").write_text("1\n")
sh("git init -q -b main && git add -A && git -c user.email=t@t -c user.name=t commit -qm init && git branch integration && git branch landing")
(W / "ledger" / "changelog").mkdir(parents=True)
(W / "team.toml").write_text(f'''repo = "{REPO}"
integration = "integration"
worktree_root = "{ROOT}"
guard = "Kong"
[[lanes]]
name = "A"
path = "A"
[[assistants]]
name = "Perkins"
[[assistants]]
name = "Nagatha"
[layers]
order = ["A/libs", "A/kits"]
[land]
check = ""
seed_index = false
test = "true"
gates = ""
guard_ledger = "{W / 'ledger'}"
notify = "echo {{kind}} {{to}} {{text}} >> {W / 'notify.log'}"
owner_notify = "true"
''')
land("install-hook")

print("== an ordinary work order is checked and reviewed before landing")
r = wo("w1", "A/v.py", "2\n")
t("land reports the passing integration check", r.returncode == 0 and "Stage 2 passed" in r.stdout, r.stdout + r.stderr)
land("queue-run", "--once")
t("a pending verdict keeps it off landing", not landed("w1"), land("queue").stdout)
run()
t("it lands after the clean Stage 3 verdict", landed("w1"), land("queue").stdout)
row = [json.loads(x) for x in (ROOT / "land" / "landed.log").read_text().splitlines() if '"hash"' in x][-1]
t("landed.log records review before and its feature (itself)",
  row["review"] == "before" and row["feature"] == "w1", row)
n = notes()
t("Nagatha alone is asked for the feature round",
  "REQUEST Nagatha Review after landing" in n and "feature w1 round 1" in n
  and "REQUEST Perkins Review after landing" not in n
  and "REQUEST Kong Review after landing" not in n, n[-600:])
kn = [line for line in n.splitlines() if "REQUEST Kong Stage 3 review" in line]
t("Kong gets one Stage 3 request for w1's own changes",
  len(kn) == 1 and "w1" in kn[0] and "--not refs/heads/landing refs/heads/integration" in kn[0] and " show " not in kn[0], kn)
t("Nagatha's request names the layer check", "layers" in n.split("REQUEST Nagatha", 1)[-1].split("\n")[0])
t("security review is not requested without security_paths", "REQUEST Perkins Stage 3" not in n)

print("== a tagged feature is reviewed when its last work order lands")
wo("f1", "A/f1.py", tag=("--feature", "feat-x"))
tree2 = Path(land("wo-cut", "A", "f2").stdout.strip())
land("wo-tag", "f2", "--feature", "feat-x")
run()
fr = json.loads((ROOT / "land" / "features" / "feat-x.json").read_text())
t("after f1 lands, f2 is still open: no round yet", landed("f1") and fr["rounds"] == [], fr)
(tree2 / "A" / "f2.py").write_text("x\n")
sh("git add -A && git -c user.email=t@t -c user.name=l commit -qm f2", cwd=tree2)
land("land", "f2")
run()
fr = json.loads((ROOT / "land" / "features" / "feat-x.json").read_text())
t("after f2 lands, with no feature-done, the round waits (feature_wait_hours)", fr["rounds"] == [], fr)
r = land("feature-done", "feat-x")
fr = json.loads((ROOT / "land" / "features" / "feat-x.json").read_text())
t("feature-done starts one round holding both", "review started" in r.stdout and len(fr["rounds"]) == 1
  and fr["rounds"][0]["wos"] == ["f1", "f2"], (r.stdout, fr))

print("== findings name work orders and come back as fix-forward requests (condition 1)")
r = land("finding", "feat-x", "--zone", "A", "--where", "A/f1.py:1", "--severity", "2", "--kind", "spec", "--what", "x",
         session="Kong")
t("a finding with no work order is refused", r.returncode != 0 and "--wo" in r.stderr + r.stdout, r.stdout + r.stderr)
r = land("finding", "feat-x", "--wo", "w1", "--zone", "A", "--where", "A/f1.py:1", "--severity", "2", "--kind", "spec",
         "--what", "x", session="Kong")
t("a work order outside the feature is refused", r.returncode != 0 and "not landed work orders of feature" in r.stderr, r.stderr)
r = land("finding", "feat-x", "--wo", "f1", "--wo", "f2", "--zone", "A", "--where", "A/f1.py:1", "--severity", "2",
         "--kind", "boundary", "--what", "belongs in a lower kit", "--belongs", "libs/core", session="Kong")
fid = r.stdout.strip()
t("a good finding gets an id", fid == "feat-x#1", r.stdout + r.stderr)
n = notes()
t("one FIX-FORWARD REQUEST to Coord-A names the zone and both work orders",
  n.count(f"REQUEST Coord-A FIX-FORWARD {fid}") == 1 and "zone A" in n and "work orders f1, f2" in n, n[-500:])
r = land("finding", "feat-x", "--same-as", fid, session="Perkins")
n2 = notes()
t("--same-as adds Perkins to it with no second request", "agrees" in r.stdout and n2.count("FIX-FORWARD") == 1)
f = json.loads((ROOT / "land" / "findings" / "feat-x.json").read_text())[0]
t("the findings file holds the entry", f["wos"] == ["f1", "f2"] and f["also"] == ["Perkins"] and f["state"] == "open", f)
r = land("finding", "feat-x", "--wo", "f1", "--zone", "A", "--where", "A/f1.py:1", "--severity", "2",
         "--kind", "security", "--what", "another issue", session="Perkins")
pid = r.stdout.strip()
n = notes()
t("Perkins finding goes to the orchestrator", pid == "feat-x#2" and n.count(f"REQUEST orc FIX-FORWARD {pid}") == 1, n[-500:])

print("== a fix-forward closes its finding when it lands")
wo("fix1", "A/f1.py", "fixed\n", tag=("--fixes", fid))
run()
f = json.loads((ROOT / "land" / "findings" / "feat-x.json").read_text())[0]
t("the finding is closed, fixed by fix1", f["state"] == "closed" and f["fixed_by"] == "fix1", f)

print("== landed first time")
ft = {x["wo"]: x for x in json.loads(land("first-time", "--json").stdout)}
t("f1 drew findings: not first time", ft["f1"]["first_time"] == "no" and ft["f1"]["findings"] == [fid, pid], ft.get("f1"))
t("w1 is pending until its days pass", ft["w1"]["first_time"] == "pending", ft.get("w1"))
ft0 = {x["wo"]: x for x in json.loads(land("first-time", "--json", "--days", "0").stdout)}
t("with 0 days w1 is yes (its window has passed)", ft0["w1"]["first_time"] == "yes", ft0["w1"])
land("finding-drop", fid, "--reason", "not real")
land("finding-drop", pid, "--reason", "not real")
ft = {x["wo"]: x for x in json.loads(land("first-time", "--json").stdout)}
t("a dropped finding does not count (pending again)", ft["f1"]["first_time"] == "pending", ft["f1"])

print("== Kong records his review and changelog line")
(W / "ledger" / "changelog" / "w1.md").write_text("Kong: w1 sets v to 2.")
r = land("reviewed", "w1", session="Kong")
review_path = ROOT / "land" / "reviews" / "w1.json"
review = json.loads(review_path.read_text()) if review_path.exists() else {}
t("Kong's Stage 3 review remains recorded; a duplicate is refused", r.returncode == 5 and review.get("state") == "land" and review.get("reviewers") == {"Kong": "pass"}, review)
t("review creates no docs-kong work order", not (ROOT / "land" / "wo" / "docs-kong-w1.json").exists()
  and not landed("docs-kong-w1"), r.stdout + r.stderr)
t("the duplicate verdict names Stage 3 and does not requeue", "Stage 3" in r.stderr and land("queue").stdout.strip() == "queue empty", r.stdout + r.stderr)

print("== the layer check")
def lay(name, files):
    tr = Path(land("wo-cut", "A", name).stdout.strip())
    for d, txt in files.items():
        (tr / d).parent.mkdir(parents=True, exist_ok=True)
        (tr / d).write_text(txt)
    sh("git add -A && git -c user.email=t@t -c user.name=l commit -qm " + name, cwd=tr)
    land("land", name)
    run()
lay("lay0", {"A/libs/core/Package.swift": '.package(path: "../../kits/top")\n', "A/kits/top/x.txt": "x\n"})
lay("lay1", {"A/libs/base/Cargo.toml": '[dependencies]\ntop = { path = "../../kits/top" }\n'})
r = land("layers")
t("a lower layer depending on a higher one is named, with its manifest line", r.returncode == 1 and
  "LAYER A/libs/core (A/libs) depends on A/kits/top (A/kits): A/libs/core/Package.swift:1" in r.stdout
  and "2 violations" in r.stdout, r.stdout + r.stderr)
r = land("layers", "--feature", "lay1")
t("--feature lists only the violation its round introduced", r.returncode == 1 and "A/libs/base" in r.stdout
  and "A/libs/core" not in r.stdout and "1 violation" in r.stdout, r.stdout + r.stderr)
r = land("findings", "--zone", "nowhere")
t("findings --zone filters by zone", "no findings" in r.stdout and "feat-x#1" in land("findings", "--zone", "A").stdout,
  r.stdout)

print(f"\n{'all passed' if not fails else f'{fails} failed'}  ({W})")
sys.exit(1 if fails else 0)
