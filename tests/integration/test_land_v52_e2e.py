"""Integration: branch flow v5.2's Stages 2 and 3 end to end, on throwaway repos and teams,
as v5.4 runs them: the fixture team has moved over (it has a `landing` branch), Kong reviews each
work order at Stage 3 before it lands, Stage 4 lands on landing, and integration moves only when Stage 7 promotes.
Each case builds its own repo with path lanes, a team manifest whose notices go to a file, and runs the real
bin/codeteam-land: `land` (Stage 2), `reviewed` (Stage 3) and `queue-run --once` (Stage 4).
  1. Two work orders change the same line; both pass Stage 2 and review. At Stage 4 the second conflicts: it is not
     landed, leaves the queue, its zone is told with the file and the landed work order named and to wait for its
     promote, then merge integration (A2), and the conflict is logged.
  2. Two work orders change different files of one zone; the second's checked zone was changed by the first after
     its base, so Stage 4 lands it and writes one recheck line naming both.
  3. A lane whose test hangs, run through a throwaway build queue (real runner, fake launchctl): Stage 2 exits 3,
     the run is recorded HUNG, and nothing is queued.
  4. A docs-only work order runs no tests at Stage 2, still waits for Stage 3 review, and then lands.
  5. A v5.1 queue entry ({wos, queued, state}) ahead of a v5.2 entry: one `queue-run --once` moves the old entry to
     land/queue-stale/, tells the orchestrator once, and lands the next entry without raising.
Landing sets:
  6. Two work orders in zones A and B, each failing the integration group without the other: alone each fails
     Stage 2; with --with they pass as one queue entry, which lands only once both are reviewed, with refs/landed
     refs.
  7. A set whose second member conflicts at Stage 4 (another landing changed its file first) bounces every member,
     names the conflicting one, and leaves landing where it was.
  8. A repo with tests/integration: Stage 2 runs it, through a throwaway build queue, under the integration group.
  9. A set reaching zones A and B compiles both in the first member's tree, one after the other: both checks pass
     and neither fails on zone-tool's guard file.
Stage 6 and Stage 4 recovery:
 10. A local validate clone whose installed land-check is the v5.1 copy (five arguments): `validate-run --once`
     reinstalls it from this codeteam-land and the Stage 6 run passes, where the stale copy recorded "toolchain".
 11. A reused land/itest worktree with a tracked file a test changed and an untracked file where M has one:
     `recheck-run --once` recovers with the forced checkout, runs the recheck at M, and untracked build output stays.
 12. Both checkouts fail (index.lock held): the result is recorded with checkout "failed", the orchestrator is told
     once and the row is marked done; no review is asked, since Kong reviewed the work order before it landed.
Repo test folders:
 13. A tests/integration folder mixing a pytest file and plain scripts, one of which fails: Stage 2 fails with exit 3
     on that step, and the scripts after the failing one still ran.
 14. A repo with tests/unit: Stage 2 runs it, through a throwaway build queue, under the unit group.
Review before landing, the move-over, Stages 6 and 7:
 15. Two separate entries are asked of Kong at once; the later one, reviewed first, lands first, and the earlier one
     lands once reviewed.
 16. A team with no landing branch: `land` refuses and `validate-run` idles with "not moved to v5.4". migrate-v54
     puts landing at the old integration and integration at base, writes the move recheck line and asks Kong for
     the backlog of the one zone it changed; the hook stops a hand move of landing. Stage 6 waits for the move
     recheck, then validates T (tagged v54) and Stage 7 moves main and integration to T. Kong closes backlog-A.
 17. With a review finding open on p1, Stage 6 validates p1's commit C and Stage 7 promotes it: review findings are
     never read (A3). The fix p2, cut from the promoted integration, lands with --fixes in another file, closes the
     finding, and is promoted in turn.
 18. A validation test that fails at C1 opens one fix (validation#1) and main stays; still failing at C2, it adds C2
     to that fix and opens no other; passing at C3, where a fix in another file lands without conflicting with the
     unpromoted defect, that run closes the fix and Stage 7 moves main to C3 in the same `validate-run --once` (A3).
Joins: codeteam-land's Stages 2 to 7 and migrate-v54 with git, its branch hook, zone-tool, land-check, the build
queue runner and the hang rule.
Skipped unless CODETEAM_TEST_GROUP=integration. Nothing outside a temp folder is touched (HOME is the temp folder's);
no live team is told."""
import json
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("CODETEAM_TEST_GROUP", "unit") != "integration",
                                reason="integration group only; run with CODETEAM_TEST_GROUP=integration")

HOME = Path(__file__).resolve().parents[2]
LAND = str(HOME / "bin" / "codeteam-land")
GATE = 3


def sh(cmd, cwd):
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, f"setup failed: {cmd}\n{r.stdout}{r.stderr}"
    return r.stdout


class Throwaway:
    """A repo with path lanes A and B (and any extra lane lines), a team manifest, and the landing tool on it."""

    def __init__(self, w: Path, lanes_extra: str = "", env_extra: str = "", moved: bool = True):
        self.w, self.repo = w, w / "repo"
        self.repo.mkdir()
        for z in ("A", "B"):
            (self.repo / z).mkdir()
            (self.repo / z / "value").write_text("1\n")
            (self.repo / z / "other").write_text("1\n")
        (self.repo / "run-tests.sh").write_text('echo "$1 $CODETEAM_TEST_GROUP" >> "$GATE_LOG"\n')
        sh("git init -q -b main && git add -A && git -c user.email=t@t -c user.name=t commit -qm init "
           "&& git branch integration" + (" && git branch landing" if moved else ""), self.repo)
        (w / "tmp").mkdir()
        (w / "team.toml").write_text(f'''repo = "{self.repo}"
integration = "integration"
worktree_root = "{w / 'team'}"
guard = "Kong"
[[lanes]]
name = "A"
path = "A"
[[lanes]]
name = "B"
path = "B"
{lanes_extra}
[env]
CODETEAM_OWNS = ""
GATE_LOG = "{w / 'gate.log'}"
TMPDIR = "{w / 'tmp'}/"
{env_extra}
[land]
check = "true"
test = "sh run-tests.sh {{zone}}"
gates = ""
seed_index = false
interface = false
notify = "echo {{kind}} {{to}} {{text}} >> {w / 'notify.log'}"
owner_notify = "true"
''')

    def land(self, *args, session=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CODETEAM_", "HERDR_"))}
        env["GATE_LOG"] = str(self.w / "gate.log")
        # Stage 6's land-check keeps its log under $HOME/land-check-logs: keep it here.
        env["HOME"] = str(self.w / "home")
        # With no ~/.gitconfig under that HOME, git 2.56 refuses the set merge without an identity.
        for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@t"), ("GIT_COMMITTER_NAME", "t"),
                     ("GIT_COMMITTER_EMAIL", "t@t")):
            env.setdefault(k, v)
        if session:
            env["CODETEAM_SESSION"] = session        # finding, reviewed and promote say who asks
        return subprocess.run([LAND, str(self.w / "team.toml"), *args], capture_output=True, text=True, env=env)

    def cut(self, zone, wo):
        r = self.land("wo-cut", zone, wo)
        assert r.returncode == 0, r.stdout + r.stderr
        return Path(r.stdout.strip())

    def edit(self, wo, path, text):
        tree = Path(self.wo(wo)["tree"])
        (tree / path).parent.mkdir(parents=True, exist_ok=True)
        (tree / path).write_text(text + "\n")
        sh(f"git add -A && git -c user.email=t@t -c user.name=lead commit -qm {wo}", tree)
        return tree

    def wo(self, wo):
        return json.loads((self.w / "team" / "land" / "wo" / f"{wo}.json").read_text())

    def integ(self, path):
        """A file as landed: Stage 4 lands on landing; integration only moves when Stage 7 promotes."""
        return sh(f"git show landing:{path}", self.repo).strip()

    def tip(self, branch="landing"):
        return sh(f"git rev-parse {branch}", self.repo).strip()

    def review(self, *wos):
        """Kong passes each work order's Stage 3 review, which lets its entry land."""
        for wo in wos:
            r = self.land("reviewed", wo, session="Kong")
            assert r.returncode == 0, r.stdout + r.stderr

    def queued(self):
        return sorted(p.name for p in (self.w / "team" / "land" / "queue").glob("*.json"))

    def gate_runs(self):
        p = self.w / "gate.log"
        return p.read_text().splitlines() if p.exists() else []

    def notices(self, settle=3.0):
        """Notices are started and not waited for: let them arrive, then read them."""
        p = self.w / "notify.log"
        deadline = time.monotonic() + settle
        while time.monotonic() < deadline:
            time.sleep(0.2)
        return p.read_text().splitlines() if p.exists() else []

    def landed_log(self):
        p = self.w / "team" / "land" / "landed.log"
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []


@pytest.fixture
def team(tmp_path):
    return Throwaway(tmp_path)


def test_a_conflict_at_stage_3_goes_back_to_the_zone(team):
    team.cut("A", "x1")
    team.cut("A", "x2")
    team.edit("x1", "A/value", "7")
    team.edit("x2", "A/value", "8")
    for wo in ("x1", "x2"):                       # both pass Stage 2 against the same integration
        r = team.land("land", wo)
        assert r.returncode == 0, r.stdout + r.stderr
    assert len(team.queued()) == 2
    team.review("x1", "x2")
    first = team.land("queue-run", "--once")
    second = team.land("queue-run", "--once")
    assert "Traceback" not in first.stderr + second.stderr, first.stderr + second.stderr
    assert team.integ("A/value") == "7"
    assert team.tip("integration") == team.tip("main")       # Stage 4 never moves integration
    assert team.queued() == []
    assert "conflict in A/value" in second.stdout
    bounce = team.w / "team" / "land" / "wo" / "x2.bounce.txt"
    assert bounce.read_text().split() == ["A/value"]
    assert "queued" not in team.wo("x2")
    assert [r for r in team.landed_log() if r.get("result") == "conflict"] and \
        [r["wos"] for r in team.landed_log() if r.get("result") == "conflict"] == [["x2"]]
    told = [line for line in team.notices() if line.startswith("NOTE Coord-A ") and "x2 did not land" in line]
    assert len(told) == 1 and "A/value" in told[0], team.notices(0)
    # A2: it names the landed work order it met and says to wait for its promote, then merge integration.
    assert "x1" in told[0] and "wait until those are promoted" in told[0] and "merge integration" in told[0], told[0]


def test_a_real_overlap_writes_one_recheck_line(team):
    team.cut("A", "o1")
    team.cut("A", "o2")
    team.edit("o1", "A/value", "2")
    team.edit("o2", "A/other", "3")               # the same zone, another file: no conflict
    for wo in ("o1", "o2"):
        r = team.land("land", wo)
        assert r.returncode == 0, r.stdout + r.stderr
    team.review("o1", "o2")
    team.land("queue-run", "--once")
    r = team.land("queue-run", "--once")
    assert r.returncode == 0 and "Traceback" not in r.stderr, r.stdout + r.stderr
    assert (team.integ("A/value"), team.integ("A/other")) == ("2", "3")
    rows = [json.loads(line) for line in (team.w / "team" / "land" / "recheck.jsonl").read_text().splitlines()]
    tip = team.tip()
    assert len(rows) == 1
    assert (rows[0]["M"], rows[0]["wo"], rows[0]["overlapping"]) == (tip, "o2", ["o1"])
    assert "A" in rows[0]["zones"]
    landed = [r for r in team.landed_log() if r.get("hash")]
    assert [(r["wos"], r["recheck"]) for r in landed] == [(["o1"], False), (["o2"], True)]


def queue_env(tmp_path):
    """[env] lines for a throwaway build queue: its runner is the real bin/codeteam-buildq, started by
    zone/tests/fake-launchctl, never the live launchd job."""
    stub = tmp_path / "stub"
    stub.mkdir()
    (stub / "tmutil").write_text("#!/bin/sh\nexit 0\n")   # the runner never touches the real Time Machine settings
    (stub / "tmutil").chmod(0o755)
    (tmp_path / "run" / "queue").mkdir(parents=True)
    (tmp_path / "run" / "queue.toml").write_text("budget = 1\n")
    (tmp_path / "load").write_text("0.5\n0\n")
    (tmp_path / "slots").mkdir()
    env = {
        "PATH": f"{stub}:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "CODETEAM_QUEUE_DIR": tmp_path / "run" / "queue",
        "CODETEAM_BUILDQ_LAUNCH": HOME / "zone" / "tests" / "fake-launchctl",
        "CODETEAM_BUILDQ": HOME / "bin" / "codeteam-buildq",
        "CODETEAM_BUILDQ_TICK": "0.05",
        "CODETEAM_BUILDQ_IDLE_EXIT": "1",
        "CODETEAM_BUILDQ_LOAD_FILE": tmp_path / "load",
        "CODETEAM_SLOT_DIR": tmp_path / "slots",
        "CODETEAM_HANG_WINDOW": "2",
        "CODETEAM_HANG_CPU_PCT": "1",
    }
    return "".join(f'{k} = "{v}"\n' for k, v in env.items())


def stop_queue(tmp_path):
    try:
        pid = json.loads((tmp_path / "run" / "queue-runner.json").read_text())["pid"]
        os.kill(pid, signal.SIGTERM)
    except (OSError, ValueError, KeyError):
        pass


def commit_main(t, msg):
    """Commit the throwaway repo's new files on main and start integration and landing there again (before any
    wo-cut)."""
    sh(f"git add -A && git -c user.email=t@t -c user.name=t commit -qm {msg} && git branch -f integration main "
       "&& git branch -f landing main", t.repo)


@pytest.fixture
def queued_team(tmp_path):
    """A team with lane H whose own test is a silent sleep, run through a throwaway build queue."""
    lane = '[[lanes]]\nname = "H"\npath = "H"\ntest = "sleep 300"\n'
    t = Throwaway(tmp_path, lanes_extra=lane, env_extra=queue_env(tmp_path))
    (t.repo / "H").mkdir()
    (t.repo / "H" / "value").write_text("1\n")
    commit_main(t, "H")
    yield t
    stop_queue(tmp_path)


def test_a_hung_test_through_the_build_queue_fails_stage_2_with_exit_3(queued_team):
    t = queued_team
    t.cut("H", "h1")
    tree = t.edit("h1", "H/value", "2")
    r = t.land("land", "h1")
    assert r.returncode == GATE, (r.returncode, r.stdout, r.stderr)
    assert t.queued() == []
    jobs = [json.loads(p.read_text()) for p in (t.w / "run" / "queue").glob("*.json")]
    assert jobs and all(j["kind"] == "run" for j in jobs), jobs   # it ran through the queue, not here
    records = [json.loads(p.read_text()) for p in tree.glob(".test-record*.json")]
    assert records and all(rec["result"] == "HUNG" and rec["exit"] == 124 for rec in records), records


def test_a_docs_only_work_order_runs_no_tests_and_lands(team):
    team.cut("A", "d1")
    team.edit("d1", "A/README.md", "# A")
    before = team.gate_runs()
    r = team.land("land", "d1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert team.gate_runs() == before
    assert len(team.queued()) == 1
    asked = [line for line in team.notices() if line.startswith("REQUEST Kong ") and " d1 " in line]
    assert len(asked) == 1, team.notices(0)               # docs-only still needs Stage 3 review
    r = team.land("queue-run", "--once")
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(team.queued()) == 1                        # not reviewed yet: it waits
    team.review("d1")
    r = team.land("queue-run", "--once")
    assert r.returncode == 0, r.stdout + r.stderr
    assert team.integ("A/README.md") == "# A"
    assert team.queued() == []


def test_a_v51_entry_is_set_aside_once_and_the_next_entry_lands(team):
    team.cut("A", "old1")
    team.edit("old1", "A/value", "5")
    old = team.w / "team" / "land" / "queue" / "20000101-000000-old1.json"   # sorts ahead of any v5.2 entry
    old.write_text(json.dumps({"wos": ["old1"], "queued": "2026-11-09T00:00:00-06:00", "state": "waiting"}))
    team.cut("B", "new1")
    team.edit("new1", "B/value", "6")
    r = team.land("land", "new1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert team.queued()[0] == old.name
    team.review("new1")
    r = team.land("queue-run", "--once")
    assert "Traceback" not in r.stderr, r.stderr
    assert (team.w / "team" / "land" / "queue-stale" / old.name).exists()
    assert team.queued() == []
    assert team.integ("B/value") == "6"
    assert team.integ("A/value") == "1"
    told = [line for line in team.notices() if line.startswith("NOTE orc ")]
    assert len(told) == 1 and "old1" in told[0], team.notices(0)


# ---------------------------------------------------------------- landing sets

COUPLED = """echo "$1 $CODETEAM_TEST_GROUP" >> "$GATE_LOG"
if [ "$CODETEAM_TEST_GROUP" = integration ] && [ "$(cat A/value)" != "$(cat B/value)" ]; then
  echo "A/value and B/value differ"; exit 1
fi
"""


def test_a_set_that_only_works_together_lands_as_one_entry(team):
    (team.repo / "run-tests.sh").write_text(COUPLED)      # units pass alone; the integration group needs both
    commit_main(team, "coupled")
    base = team.tip()
    team.cut("A", "a1")
    team.cut("B", "b1")
    trees = {"a1": team.edit("a1", "A/value", "2"), "b1": team.edit("b1", "B/value", "2")}
    tips = {wo: sh("git rev-parse HEAD", tree).strip() for wo, tree in trees.items()}
    for wo in ("a1", "b1"):                               # each alone breaks the integration group
        r = team.land("land", wo)
        assert r.returncode == GATE, (wo, r.returncode, r.stdout, r.stderr)
        assert "A/value and B/value differ" in r.stdout, r.stdout
    assert team.queued() == []
    r = team.land("land", "a1", "--with", "b1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(team.queued()) == 1
    entry = json.loads((team.w / "team" / "land" / "queue" / team.queued()[0]).read_text())
    assert [wo for wo, _ in entry["tips"]] == ["a1", "b1"]
    team.review("a1")
    r = team.land("queue-run", "--once")
    assert len(team.queued()) == 1                        # the set lands only once every member is reviewed
    team.review("b1")
    r = team.land("queue-run", "--once")
    assert r.returncode == 0 and "Traceback" not in r.stderr, r.stdout + r.stderr
    assert team.queued() == []
    assert (team.integ("A/value"), team.integ("B/value")) == ("2", "2")
    for wo in ("a1", "b1"):
        assert sh(f"git rev-parse refs/landed/{wo}", team.repo).strip() == tips[wo]
    landed = [row for row in team.landed_log() if row.get("hash")]
    assert [row["wos"] for row in landed] == [["a1"], ["b1"]]
    assert landed[0]["range"].split("..")[0] == base       # the first member merges onto the set's base
    assert landed[1]["range"].split("..")[0] == landed[0]["hash"]
    assert landed[1]["hash"] == team.tip()


def test_a_set_whose_second_member_conflicts_bounces_every_member(team):
    team.cut("A", "s1")
    team.cut("B", "s2")
    team.cut("B", "c1")
    team.edit("s1", "A/value", "3")
    team.edit("s2", "B/value", "3")
    team.edit("c1", "B/value", "9")
    r = team.land("land", "c1")
    assert r.returncode == 0, r.stdout + r.stderr
    r = team.land("land", "s1", "--with", "s2")
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(team.queued()) == 2
    team.review("c1", "s1", "s2")
    r = team.land("queue-run", "--once")                  # c1 lands first and changes B/value
    assert team.integ("B/value") == "9", r.stdout + r.stderr
    before = team.tip()
    r = team.land("queue-run", "--once")
    assert "Traceback" not in r.stderr, r.stderr
    assert team.tip() == before
    assert (team.integ("A/value"), team.integ("B/value")) == ("1", "9")
    assert team.queued() == []
    for wo in ("s1", "s2"):
        assert subprocess.run(["git", "rev-parse", "--verify", "-q", f"refs/landed/{wo}"], cwd=team.repo,
                              capture_output=True).returncode != 0
        assert "queued" not in team.wo(wo)
    bounces = team.w / "team" / "land" / "wo"
    assert (bounces / "s2.bounce.txt").read_text().split() == ["B/value"]
    assert "s2" in (bounces / "s1.bounce.txt").read_text()
    assert [row["wos"] for row in team.landed_log() if row.get("result") == "conflict"] == [["s1", "s2"]]
    told = team.notices()
    assert [line for line in told if line.startswith("NOTE Coord-A ") and "s1 did not land" in line and "s2" in line], told
    assert [line for line in told if line.startswith("NOTE Coord-B ") and "s2 did not land" in line
            and "B/value" in line], told


@pytest.fixture
def repo_itest_team(tmp_path):
    """A team whose repo has tests/integration/check.sh, which logs the group it ran under; the step goes through
    a throwaway build queue."""
    t = Throwaway(tmp_path, env_extra=queue_env(tmp_path))
    (t.repo / "tests" / "integration").mkdir(parents=True)
    (t.repo / "tests" / "integration" / "check.sh").write_text(
        'echo "repo-integration ${CODETEAM_TEST_GROUP:-none}" >> "$GATE_LOG"\n')
    commit_main(t, "itest")
    yield t
    stop_queue(tmp_path)


def test_stage_2_runs_the_repo_integration_tests_under_the_integration_group(repo_itest_team):
    t = repo_itest_team
    t.cut("A", "i1")
    t.edit("i1", "A/value", "4")
    r = t.land("land", "i1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS integration tests (tests/integration)" in r.stdout, r.stdout
    assert [line for line in t.gate_runs() if line.startswith("repo-integration")] == \
        ["repo-integration integration"], t.gate_runs()
    assert len(t.queued()) == 1


def test_a_set_reaching_two_zones_compiles_both_in_one_tree(tmp_path):
    check = tmp_path / "check.sh"
    check.write_text('sleep 1; echo "check $*" >> "$GATE_LOG"\n')   # long enough that two at once would overlap
    t = Throwaway(tmp_path, env_extra=f'ZONE_CHECK_CMD = "sh {check}"\n')
    t.cut("A", "k1")
    t.cut("B", "k2")
    t.edit("k1", "A/value", "5")
    t.edit("k2", "B/value", "5")
    r = t.land("land", "k1", "--with", "k2")
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "PASS compile A (A)" in out and "PASS compile B (B)" in out, out
    assert "Traceback" not in out and "codeteam-test-guards" not in out, out
    assert sorted(line for line in t.gate_runs() if line.startswith("check")) == ["check A", "check B"], t.gate_runs()
    assert len(t.queued()) == 1


# ---------------------------------------------------------------- Stage 6 and Stage 4 recovery

def test_a_stale_land_check_is_reinstalled_before_the_stage6_run(tmp_path):
    t = Throwaway(tmp_path)
    clone = tmp_path / "validate"
    with open(tmp_path / "team.toml", "a") as f:
        f.write(f'[land.validate]\nlocal = true\npath = "{clone}"\nsuite = "true"\ntoolchain = ["true"]\n')
    r = t.land("alpha-install")
    assert r.returncode == 0, r.stdout + r.stderr
    installed = clone / ".git" / "land-check"
    fresh = installed.read_text()
    v52 = "h=$1; suite=$2; fp_cmd=$3; want=$4"
    assert v52 in fresh
    installed.write_text(fresh.replace(v52, "h=$1; suite=$2; limit=$3; fp_cmd=$4; want=$5"))   # the Nov 8 copies
    h = t.tip()                                           # nothing has landed: Stage 6 takes landing's tip
    r = t.land("validate-run", "--once")
    assert r.returncode == 0 and "Traceback" not in r.stderr, r.stdout + r.stderr
    rows = [json.loads(line) for line in (t.w / "team" / "land" / "validation-results.jsonl").read_text().splitlines()]
    assert [(row["commit"], row["result"]) for row in rows] == [(h, "pass")], rows
    assert installed.read_text() == fresh


def landed_with_recheck(team):
    """o1 changes A/value and o2 adds A/new; both pass review and o2 lands after o1 with one recheck row at M,
    landing's tip."""
    base = team.tip()
    team.cut("A", "o1")
    team.cut("A", "o2")
    team.edit("o1", "A/value", "2")
    team.edit("o2", "A/new", "from o2")
    for wo in ("o1", "o2"):
        r = team.land("land", wo)
        assert r.returncode == 0, r.stdout + r.stderr
    team.review("o1", "o2")
    team.land("queue-run", "--once")
    team.land("queue-run", "--once")
    M = team.tip()
    rows = [json.loads(line) for line in (team.w / "team" / "land" / "recheck.jsonl").read_text().splitlines()]
    assert [(row["M"], row["wo"]) for row in rows] == [(M, "o2")] and "done" not in rows[0]
    itest = team.w / "team" / "land" / "itest"
    sh(f"git worktree add -q --detach {itest} {base}", team.repo)     # an earlier recheck's tree, reused
    return M, itest


def recheck_state(team):
    land = team.w / "team" / "land"
    rows = [json.loads(line) for line in (land / "recheck.jsonl").read_text().splitlines()]
    results = [json.loads(line) for line in (land / "integration-results.jsonl").read_text().splitlines()]
    feature = json.loads((land / "features" / "o2.json").read_text())
    return rows, results, feature


def test_a_dirty_itest_tree_is_recovered_by_the_forced_checkout(team):
    M, itest = landed_with_recheck(team)
    (itest / "A" / "value").write_text("a test wrote here\n")          # tracked, changed by a test
    (itest / "A" / "new").write_text("left by a test\n")                # untracked, where M has a file
    (itest / "build").mkdir()
    (itest / "build" / "out.o").write_text("warm\n")                    # untracked build output
    before = len(team.gate_runs())
    r = team.land("recheck-run", "--once")
    assert r.returncode == 0 and "Traceback" not in r.stderr, r.stdout + r.stderr
    assert sh("git rev-parse HEAD", itest).strip() == M
    assert ((itest / "A" / "value").read_text(), (itest / "A" / "new").read_text()) == ("2\n", "from o2\n")
    assert (itest / "build" / "out.o").read_text() == "warm\n"
    assert "A integration" in team.gate_runs()[before:], team.gate_runs()    # the recheck ran zone A's tests
    rows, results, feature = recheck_state(team)
    assert "done" in rows[0]
    assert len(results) == 1 and "checkout" not in results[0], results
    assert feature["rounds"], feature                                      # handed to review


def test_a_checkout_that_cannot_be_forced_is_recorded_and_asks_no_review(team):
    M, itest = landed_with_recheck(team)
    asked_before = kong_requests(team)
    (itest / "A" / "value").write_text("a test wrote here\n")
    lock = team.repo / ".git" / "worktrees" / "itest" / "index.lock"
    lock.write_text("")                                                   # git cannot write the index at all
    before = len(team.gate_runs())
    r = team.land("recheck-run", "--once")
    assert r.returncode == 0 and "Traceback" not in r.stderr, r.stdout + r.stderr
    assert sh("git rev-parse HEAD", itest).strip() != M
    rows, results, feature = recheck_state(team)
    assert "done" in rows[0]
    assert len(results) == 1, results
    assert (results[0]["checkout"], results[0]["set"]) == ("failed", ["o2"]) and "index.lock" in results[0]["error"]
    assert team.gate_runs()[before:] == []                                # no test ran at a commit not checked out
    assert feature["rounds"], feature
    told = team.notices()
    assert len([line for line in told if line.startswith("NOTE orc ") and "Recheck checkout failed" in line
                and M[:10] in line]) == 1, told
    # v5.4: Kong reviewed o2 before it landed (Stage 3); the recheck hands nothing over and asks no review.
    assert kong_requests(team) == asked_before, told
    review = json.loads((team.w / "team" / "land" / "reviews" / "o2.json").read_text())
    assert (review["wo"], review["stage"], review["state"]) == ("o2", 3, "land"), review
    r = team.land("recheck-run", "--once")                                # done: not tried again
    assert len(recheck_state(team)[1]) == 1


# ---------------------------------------------------------------- repo test folders

@pytest.fixture
def queued_plain_team(tmp_path):
    """Lanes A and B and a throwaway build queue; each case adds its own repo test folder with commit_main."""
    t = Throwaway(tmp_path, env_extra=queue_env(tmp_path))
    yield t
    stop_queue(tmp_path)


def test_one_failing_script_fails_a_mixed_folder_and_the_rest_still_run(queued_plain_team):
    t = queued_plain_team
    folder = t.repo / "tests" / "integration"
    folder.mkdir(parents=True)
    (folder / "test_ok.py").write_text(
        'import os\n\ndef test_ok():\n    open(os.environ["GATE_LOG"], "a").write("pytest ran\\n")\n')
    (folder / "a-fails.sh").write_text('echo "a-fails ran" >> "$GATE_LOG"; echo "a-fails: broken on purpose"; exit 1\n')
    (folder / "b-passes.sh").write_text('echo "b-passes ran" >> "$GATE_LOG"\n')
    commit_main(t, "mixed")
    t.cut("A", "m1")
    t.edit("m1", "A/value", "6")
    r = t.land("land", "m1")
    assert r.returncode == GATE, (r.returncode, r.stdout, r.stderr)
    assert "FAIL integration tests (tests/integration)" in r.stdout, r.stdout
    assert "a-fails: broken on purpose" in r.stdout, r.stdout
    ran = t.gate_runs()
    assert {"pytest ran", "a-fails ran", "b-passes ran"} <= set(ran), ran   # b-passes sorts after the failure
    assert t.queued() == []


def test_stage_2_runs_the_repo_unit_tests_under_the_unit_group(queued_plain_team):
    t = queued_plain_team
    (t.repo / "tests" / "unit").mkdir(parents=True)
    (t.repo / "tests" / "unit" / "check.sh").write_text('echo "repo-unit ${CODETEAM_TEST_GROUP:-none}" >> "$GATE_LOG"\n')
    commit_main(t, "unit")
    t.cut("A", "u1")
    t.edit("u1", "A/value", "7")
    r = t.land("land", "u1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS unit tests (tests/unit)" in r.stdout, r.stdout
    assert [line for line in t.gate_runs() if line.startswith("repo-unit")] == ["repo-unit unit"], t.gate_runs()
    assert len(t.queued()) == 1


# ---------------------------------------------------------------- review before landing, move-over, Stages 6-7

def kong_requests(team):
    return [line for line in team.notices() if line.startswith("REQUEST Kong ")]


def test_separate_entries_are_reviewed_at_once_and_land_as_each_is_reviewed(team):
    team.cut("A", "r1")
    team.cut("B", "r2")
    team.edit("r1", "A/value", "2")
    team.edit("r2", "B/value", "3")
    for wo in ("r1", "r2"):
        r = team.land("land", wo)
        assert r.returncode == 0, r.stdout + r.stderr
    asked = kong_requests(team)                           # both asked at once, neither behind the other
    assert len(asked) == 2 and {" r1 " in line for line in asked} == {True, False}, asked
    assert [line for line in asked if " r2 " in line], asked
    team.review("r2")                                     # the later entry is reviewed first
    r = team.land("queue-run", "--once")
    assert r.returncode == 0 and "Traceback" not in r.stderr, r.stdout + r.stderr
    assert (team.integ("A/value"), team.integ("B/value")) == ("1", "3")
    assert len(team.queued()) == 1                        # r1 still waits for its review
    team.review("r1")
    team.land("queue-run", "--once")
    assert (team.integ("A/value"), team.integ("B/value")) == ("2", "3")
    assert [row["wos"] for row in team.landed_log() if row.get("hash")] == [["r2"], ["r1"]]


def test_an_unmoved_team_idles_and_migrate_v54_moves_it_over(tmp_path):
    t = Throwaway(tmp_path, moved=False)
    with open(tmp_path / "team.toml", "a") as f:
        f.write(f'[land.validate]\nlocal = true\npath = "{tmp_path / "validate"}"\nsuite = "true"\n'
                'toolchain = ["true"]\n')
    r = t.land("alpha-install")
    assert r.returncode == 0, r.stdout + r.stderr
    base = t.tip("main")
    sh("git checkout -q --detach integration && echo old > A/value && git add -A "     # v5.2 landed work, unpromoted
       "&& git -c user.email=t@t -c user.name=t commit -qm old && git branch -f integration HEAD "
       "&& git checkout -q main", t.repo)
    old = t.tip("integration")
    r = t.land("land", "nothing")                         # Stage 2 refuses on a team that has not moved
    assert r.returncode != 0 and "not moved to v5.4: run migrate-v54" in r.stderr, r.stdout + r.stderr
    r = t.land("validate-run", "--once")                  # the runner idles: no stage work
    assert r.returncode == 0 and "not moved to v5.4" in r.stderr, r.stdout + r.stderr
    validation = t.w / "team" / "land" / "validation-results.jsonl"
    assert not validation.exists()
    r = t.land("migrate-v54", session="orc")
    assert r.returncode == 0 and "Traceback" not in r.stderr, r.stdout + r.stderr
    assert (t.tip(), t.tip("integration"), t.tip("main")) == (old, base, base)
    rows = [json.loads(line) for line in (t.w / "team" / "land" / "recheck.jsonl").read_text().splitlines()]
    assert [(row["M"], row["wo"], row.get("move")) for row in rows] == [(old, "v54-move", True)]
    asked = kong_requests(t)                              # one backlog review, for the zone the move-over changed
    assert len(asked) == 1 and "reviewed backlog-A" in asked[0] and "backlog-B" not in asked[0], asked
    hand = subprocess.run(["git", "branch", "-f", "landing", base], cwd=t.repo, capture_output=True, text=True,
                          env={k: v for k, v in os.environ.items() if k != "CODETEAM_LAND_TOOL"})
    assert hand.returncode != 0 and t.tip() == old, hand.stdout + hand.stderr   # the hook stops a hand move
    r = t.land("validate-run", "--once")                  # Stage 6 waits for the move recheck
    assert r.returncode == 0 and "Traceback" not in r.stderr, r.stdout + r.stderr
    assert not validation.exists()
    r = t.land("recheck-run", "--once")
    assert r.returncode == 0 and "Traceback" not in r.stderr, r.stdout + r.stderr
    r = t.land("validate-run", "--once")                  # T passes, and Stage 7 promotes it
    assert r.returncode == 0 and "Traceback" not in r.stderr, r.stdout + r.stderr
    rows = [json.loads(line) for line in validation.read_text().splitlines()]
    assert [(row["commit"], row["result"], row.get("v54")) for row in rows] == [(old, "pass", True)], rows
    assert (t.tip("main"), t.tip("integration")) == (old, old)
    r = t.land("reviewed", "backlog-A", session="Kong")
    assert r.returncode == 0, r.stdout + r.stderr
    backlog = json.loads((t.w / "team" / "land" / "reviews" / "backlog-A.json").read_text())
    assert (backlog["state"], backlog["reviewed_at"]) == ("reviewed", old), backlog


def validate_team(tmp_path, suite="true"):
    t = Throwaway(tmp_path)
    with open(tmp_path / "team.toml", "a") as f:
        f.write(f'[land.validate]\nlocal = true\npath = "{tmp_path / "validate"}"\n'
                f"suite = '{suite}'\ntoolchain = [\"true\"]\n")
    r = t.land("alpha-install")                           # the validate clone Stage 6 uses
    assert r.returncode == 0, r.stdout + r.stderr
    return t


def land_reviewed(t, wo, path, text, *more):
    t.cut(path.split("/")[0], wo)
    t.edit(wo, path, text)
    r = t.land("land", wo, *more)
    assert r.returncode == 0, r.stdout + r.stderr
    t.review(wo)
    r = t.land("queue-run", "--once")
    assert r.returncode == 0 and "Traceback" not in r.stderr, r.stdout + r.stderr
    return t.tip()


def test_an_open_review_finding_does_not_hold_stage7(tmp_path):
    t = validate_team(tmp_path)
    main = t.tip("main")
    c = land_reviewed(t, "p1", "A/value", "4")
    assert c != main and t.tip("integration") == main     # landed on landing; integration waits for Stage 7
    r = t.land("finding", "p1", "--wo", "p1", "--zone", "A", "--where", "A/value:1", "--severity", "3",
               "--kind", "test", "--what", "an open finding", session="Nagatha")
    assert r.returncode == 0, r.stdout + r.stderr
    fid = r.stdout.strip().splitlines()[-1]
    r = t.land("findings", "p1", "--open")
    assert fid in r.stdout, r.stdout
    validation = t.w / "team" / "land" / "validation-results.jsonl"

    def validated():
        lines = validation.read_text().splitlines() if validation.exists() else []
        return [(row["commit"], row["result"]) for row in map(json.loads, lines)]

    r = t.land("validate-run", "--once")                  # Stage 6 passes C; Stage 7 never reads review findings
    assert r.returncode == 0 and "Traceback" not in r.stderr, r.stdout + r.stderr
    assert validated() == [(c, "pass")]
    assert (t.tip("main"), t.tip("integration")) == (c, c)
    c2 = land_reviewed(t, "p2", "A/other", "5", "--fixes", fid)   # cut from integration, now C: no conflict
    r = t.land("findings", "p1", "--open")
    assert fid not in r.stdout, r.stdout                  # the fix's landing closed it
    r = t.land("validate-run", "--once")
    assert r.returncode == 0 and "Traceback" not in r.stderr, r.stdout + r.stderr
    assert validated() == [(c, "pass"), (c2, "pass")]
    assert (t.tip("main"), t.tip("integration")) == (c2, c2)


def test_a_validation_fix_gathers_failing_commits_and_closes_on_the_pass_that_promotes(tmp_path):
    # The suite fails while A/value is "bad", unless B/other says "fixed": the fix is cut from integration, which
    # never had the bad value, so it lands in another file without conflicting with the landed defect.
    t = validate_team(tmp_path, suite='test "$(cat A/value)" != bad || test "$(cat B/other)" = fixed')
    main = t.tip("main")
    validation = t.w / "team" / "land" / "validation-results.jsonl"
    fixes = t.w / "team" / "land" / "findings" / "validation.json"

    def land_and_validate(wo, path, text):
        c = land_reviewed(t, wo, path, text)
        # Integration stays at base until a promote, so q2 and q3 land over q1's unpromoted work and get a recheck
        # line; Stage 6 takes a commit only once its recheck is finished.
        r = t.land("recheck-run", "--once")
        assert r.returncode == 0 and "Traceback" not in r.stderr, r.stdout + r.stderr
        r = t.land("validate-run", "--once")
        assert r.returncode == 0 and "Traceback" not in r.stderr, r.stdout + r.stderr
        return c

    def last_row():
        row = json.loads(validation.read_text().splitlines()[-1])
        return row["commit"], row["result"]

    c1 = land_and_validate("q1", "A/value", "bad")
    assert last_row() == (c1, "fail")
    items = json.loads(fixes.read_text())
    assert [(i["id"], i["state"], i["commits"]) for i in items] == [("validation#1", "open", [c1])], items
    assert t.tip("main") == main
    c2 = land_and_validate("q2", "B/value", "2")          # A/value is still "bad"
    assert last_row() == (c2, "fail")
    items = json.loads(fixes.read_text())
    assert [(i["id"], i["state"], i["commits"]) for i in items] == [("validation#1", "open", [c1, c2])], items
    assert t.tip("main") == main
    c3 = land_and_validate("q3", "B/other", "fixed")      # no --fixes: the passing run is what closes it
    assert last_row() == (c3, "pass")
    items = json.loads(fixes.read_text())
    assert [(i["id"], i["state"]) for i in items] == [("validation#1", "closed")], items
    assert (t.tip("main"), t.tip("integration")) == (c3, c3)
