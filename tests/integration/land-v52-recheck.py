#!/usr/bin/env -S python3 -u
"""Contracts for landing rechecks and commit evidence on real boundaries: integration tests that run
tmutil for real (team_env with no TMPDIR in the manifest, itest_checkout's new tree), the real step_results thread pool,
the real landing and findings locks and the recheck runner's flock (the recheck file, recheck_one, cmd_recheck_run), and
share/codeteam_launchd.py for the service install. The unit tests are in tests/unit/land-v52-recheck.py."""
import contextlib
import fcntl
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

# Restart markers and stage admissions live beside the queue; keep them out of the checkout.
os.environ["CODETEAM_QUEUE_DIR"] = str(Path(tempfile.mkdtemp(prefix="land-queue-")) / "queue")

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_recheck", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)

# These isolated stage fixtures represent teams that have already moved over.
cl.v54_unmoved = Mock(return_value=False)


def make_team(root):
    repo = root / "repo"
    repo.mkdir()
    manifest = root / "sample.toml"
    manifest.write_text(f'repo = "{repo}"\nworktree_root = "{root / "team"}"\n'
                        '[land]\norchestrator = "Skippy"\n')
    team = cl.Team(str(manifest))
    team.notify = Mock()
    return team


def test_environment_hang_window():
    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
        env = cl.team_env(make_team(Path(tmp)), "integration")
    assert env["CODETEAM_HANG_WINDOW"] == "600"
    assert "CODETEAM_HANG_MIN" not in env


def test_explicit_env_hang_settings_are_kept():
    # team_env makes <dir>/tmp, so the team's folders live in a temp folder, never the folder the test runs from.
    with tempfile.TemporaryDirectory() as tmp:
        team = SimpleNamespace(root=Path(tmp) / "root", dir=Path(tmp) / "land", manifest=Path(tmp) / "team.toml",
                               cfg={"hang_min": 7},
                               m={"env": {"CODETEAM_HANG_WINDOW": "2", "CODETEAM_HANG_CPU_PCT": "4"}})
        with patch.dict(os.environ, {"CODETEAM_HANG_WINDOW": "900"}, clear=True):
            env = cl.team_env(team, "unit")
        assert (env["CODETEAM_HANG_WINDOW"], env["CODETEAM_HANG_CPU_PCT"]) == ("2", "4")
        team.m = {"env": {"CODETEAM_HANG_CPU_PCT": "4"}}
        with patch.dict(os.environ, {"CODETEAM_HANG_WINDOW": "900"}, clear=True):
            env = cl.team_env(team, "unit")
        assert (env["CODETEAM_HANG_WINDOW"], env["CODETEAM_HANG_CPU_PCT"]) == ("420", "4")


def test_recheck_file_preserves_appends_and_unreadable():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        path = team.dir / "recheck.jsonl"
        path.write_text('{"M":"one"}\nnot json\n{"M":"two"}\n')
        rows = cl.read_recheck(team)
        assert rows == [{"M": "one"}, {"bad": "not json", "done": "unreadable"}, {"M": "two"}]
        assert cl.pending_recheck(rows) == 0
        with path.open("a") as f:
            f.write('{"M":"three"}\n')
        cl.mark_recheck_done(team, 0, "now")
        assert cl.read_recheck(team) == [{"M": "one", "done": "now"}, {"bad": "not json", "done": "unreadable"},
                                         {"M": "two"}, {"M": "three"}]
        assert cl.pending_recheck(cl.read_recheck(team)) == 2


def test_itest_checkout_missing():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        with patch.object(cl, "git", return_value=SimpleNamespace(returncode=0)) as git:
            assert cl.itest_checkout(team, "merge1") == team.dir / "itest"
        git.assert_called_once_with(team.repo, "worktree", "add", "--detach", str(team.dir / "itest"), "merge1", check=False)


def stamped(batches):
    """A step_results fake: the next batch, each row carrying the group keyword as the real one stamps it."""
    batches = iter(batches)
    return lambda *args, **kw: [row | ({"group": kw["group"]} if "group" in kw else {}) for row in next(batches)]


def test_step_results_outcome_tail_and_per_step_time():
    first, second = Mock(returncode=1), Mock(returncode=0)
    clock = threading.local()
    starts = iter([10, 12])
    main_thread = threading.current_thread()

    def now():
        return next(starts) if threading.current_thread() is main_thread else clock.end

    def communicate(end, text):
        clock.end = end
        return (text,)

    first.communicate.side_effect = lambda: communicate(15, "\n".join(f"line {i}" for i in range(35)))
    second.communicate.side_effect = lambda: communicate(17, "ok")
    with patch.object(cl.subprocess, "Popen", side_effect=[first, second]), \
            patch.object(cl.time, "time", side_effect=now), \
            patch.object(cl, "records_pass", return_value=False):
        results = cl.step_results("tree", [("first", "a"), ("second", "b")], {})
    assert [r["outcome"] for r in results] == ["FAIL", "PASS"]
    assert [r["name"] for r in results] == ["first", "second"]
    assert [r["seconds"] for r in results] == [5, 5]
    assert results[0]["tail"] == [f"line {i}" for i in range(5, 35)]
    assert results[1]["tail"] == ["ok"]


def test_recheck_one_open_add_close():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        rec = {"wo": "work", "zone": "A", "feature": "feature", "fixes": ["prior#1"]}
        (team.dir / "wo" / "work.landed.json").write_text(json.dumps(rec))
        rows = [{"time": "then", "M": m, "wo": "work", "overlapping": ["other"], "zones": ["A"]} for m in ("merge11111111", "merge22222222", "merge33333333")]
        path = team.dir / "recheck.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        with patch.object(cl, "itest_checkout", return_value=team.dir / "itest", create=True), \
                patch.object(cl, "recheck_steps", return_value=([("type check", "check")], [("tests A", "test")]), create=True), \
                patch.object(cl, "step_results", side_effect=stamped([
                    [{"name": "type check", "outcome": "PASS", "seconds": 1, "tail": []}],
                    [{"name": "tests A", "outcome": "FAIL", "seconds": 2, "tail": []}],
                    [{"name": "type check", "outcome": "PASS", "seconds": 1, "tail": []}],
                    [{"name": "tests A", "outcome": "FAIL", "seconds": 2, "tail": []}],
                    [{"name": "type check", "outcome": "PASS", "seconds": 1, "tail": []}],
                    [{"name": "tests A", "outcome": "PASS", "seconds": 2, "tail": []}]]), create=True), \
                patch.object(cl, "after_landing") as after, patch.object(cl, "now", return_value="now"):
            cl.recheck_one(team, [rows[0]])
            results = [json.loads(x) for x in (team.dir / "integration-results.jsonl").read_text().splitlines()]
            assert len(results) == 1 and results[0]["tests"][-1]["result"] == "fail"
            [finding] = cl.load_findings(team, "feature")
            assert (finding["id"], finding["test"], finding["Ms"], finding["kind"], finding["zone"]) == ("feature#1", "tests A", ["merge11111111"], "test", "A")
            assert cl.find_finding(team, "feature#1")["state"] == "open"
            assert team.notify.call_count == 1
            to, kind, message = team.notify.call_args.args
            assert (to, kind) == ("Coord-A", "REQUEST") and "feature#1" in message and "--fixes feature#1" in message
            assert cl.read_recheck(team)[0]["done"] == "now"
            assert after.call_count == 1 and "fixes" not in after.call_args.args[1][0]
            cl.recheck_one(team, [rows[1]])
            [finding] = cl.load_findings(team, "feature")
            assert finding["Ms"] == ["merge11111111", "merge22222222"] and team.notify.call_count == 1
            cl.recheck_one(team, [rows[2]])
            assert cl.find_finding(team, "feature#1")["state"] == "closed"
            cl.update_finding(team, "feature#1", reason="verified")
            assert cl.find_finding(team, "feature#1")["reason"] == "verified"


def test_recheck_close_records_full_closing_commit():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        finding = {"id": "feat#1", "state": "open", "by": "recheck", "test": "a", "Ms": ["11111111111111111111"]}
        (team.dir / "findings").mkdir(exist_ok=True)
        cl.save_findings(team, "feat", [finding])
        cl.apply_recheck_findings(team, {"M": "abcdef0123456789abcd"}, lambda test: ({}, {}), [{"name": "a", "result": "pass"}], "t2")
        finding = cl.find_finding(team, "feat#1")
        assert finding.get("closed_at") == "abcdef0123456789abcd"
        assert (finding["state"], finding["closed"], finding["fixed_by"], finding["reason"]) == (
            "closed", "t2", None, "passes at M abcdef0123")


def test_recheck_one_compile_failure_skips_tests():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        row = {"time": "then", "M": "merge", "wo": "work", "overlapping": [], "zones": ["A"]}
        (team.dir / "wo" / "work.landed.json").write_text(json.dumps({"wo": "work", "zone": "A"}))
        (team.dir / "recheck.jsonl").write_text(json.dumps(row) + "\n")
        with patch.object(cl, "itest_checkout", return_value=team.dir / "itest", create=True), \
                patch.object(cl, "recheck_steps", return_value=([("type check", "check")], [("tests A", "test")]), create=True), \
                patch.object(cl, "step_results", side_effect=stamped([[{"name": "type check", "outcome": "FAIL", "seconds": 1, "tail": []}]]), create=True) as steps, \
                patch.object(cl, "after_landing"), patch.object(cl, "now", return_value="now"):
            result = cl.recheck_one(team, [row])
        assert steps.call_count == 1
        assert result["tests"] == [{"name": "type check", "result": "fail", "seconds": 1.0, "group": "compile"}]


def test_recheck_one_orc_notifies_orchestrator():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        row = {"time": "then", "M": "merge", "wo": "work", "overlapping": [], "zones": ["orc"]}
        (team.dir / "wo" / "work.landed.json").write_text(json.dumps({"wo": "work", "zone": "orc"}))
        (team.dir / "recheck.jsonl").write_text(json.dumps(row) + "\n")
        with patch.object(cl, "itest_checkout", return_value=team.dir / "itest", create=True), \
                patch.object(cl, "recheck_steps", return_value=([], [("tests orc", "test")]), create=True), \
                patch.object(cl, "step_results", side_effect=stamped([[{"name": "tests orc", "outcome": "FAIL", "seconds": 1, "tail": []}]]), create=True), \
                patch.object(cl, "after_landing"), patch.object(cl, "now", return_value="now"):
            cl.recheck_one(team, [row])
        assert team.notify.call_args.args[0:2] == ("Skippy", "REQUEST")


def test_recheck_checkout_failure_records_notifies_once_and_stays_pending():
    # A recheck that ran nothing is not done, for an ordinary row as for a move.
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        row = {"time": "then", "M": "0123456789abcdef", "wo": "work-a", "set": ["work-a", "work-b"],
               "overlapping": ["prior"], "zones": ["A"]}
        recs = [{"wo": "work-a", "zone": "A"}, {"wo": "work-b", "zone": "B"}]
        for rec in recs:
            (team.dir / "wo" / f"{rec['wo']}.landed.json").write_text(json.dumps(rec))
        (team.dir / "recheck.jsonl").write_text(json.dumps(row) + "\n")
        def failed_git(*args, **kwargs):
            if kwargs.get("check", True):
                raise SystemExit(1)
            return SimpleNamespace(returncode=1, stderr="  checkout refused  ")

        with patch.object(cl, "git", side_effect=failed_git), \
                patch.object(cl, "step_results") as steps, patch.object(cl, "apply_recheck_findings") as findings, \
                patch.object(cl, "after_landing") as after, patch.object(cl, "now", return_value="now"):
            result = cl.recheck_one(team, [row])
            again = cl.recheck_one(team, [cl.read_recheck(team)[0]])      # the next poll rereads the row and fails again
        expected = {"time": "now", "M": "0123456789abcdef", "wo": "work-a", "set": ["work-a", "work-b"],
                    "overlapping": ["prior"], "zones": ["A"], "tests": [], "checkout": "failed", "error": "checkout refused",
                    "batch": ["work-a"]}
        assert result == expected
        assert again["checkout"] == "failed"
        assert [json.loads(line) for line in (team.dir / "integration-results.jsonl").read_text().splitlines()] == [expected]
        assert cl.read_recheck(team) == [{**row, "checkout_failed": "now"}]
        team.notify.assert_called_once()
        to, kind, text = team.notify.call_args.args
        assert (to, kind) == ("Skippy", "NOTE")
        assert all(s in text for s in ("0123456789", "work-a", "work-b", "checkout refused", "stays pending"))
        after.assert_not_called()
        steps.assert_not_called()
        findings.assert_not_called()


def test_recheck_findings_exception_keeps_result_and_marks_done():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        team.log = Mock()
        row = {"time": "then", "M": "merge", "wo": "work", "overlapping": [], "zones": ["A"]}
        (team.dir / "recheck.jsonl").write_text(json.dumps(row) + "\n")
        (team.dir / "wo" / "work.landed.json").write_text(json.dumps({"wo": "work", "zone": "A"}))
        with patch.object(cl, "itest_checkout", return_value=team.dir / "itest"), \
                patch.object(cl, "recheck_steps", return_value=([], [])), \
                patch.object(cl, "step_results", return_value=[]), \
                patch.object(cl, "apply_recheck_findings", side_effect=ValueError("bad finding")), \
                patch.object(cl, "after_landing"), patch.object(cl, "now", return_value="now"):
            result = cl.recheck_one(team, [row])
        assert [json.loads(line) for line in (team.dir / "integration-results.jsonl").read_text().splitlines()] == [
            {"time": "now", "M": "merge", "wo": "work", "overlapping": [], "zones": ["A"], "tests": [], "batch": ["work"]}]
        assert result["M"] == "merge"
        team.log.assert_called_once_with({"time": "now", "wos": ["work"], "recheck_findings_error": "ValueError: bad finding"})
        assert cl.read_recheck(team) == [{**row, "done": "now"}]


def test_recheck_after_landing_holds_land_lock():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        row = {"time": "then", "M": "merge", "wo": "work", "overlapping": [], "zones": ["A"]}
        (team.dir / "recheck.jsonl").write_text(json.dumps(row) + "\n")
        (team.dir / "wo" / "work.landed.json").write_text(json.dumps({"wo": "work", "zone": "A"}))
        blocked = []

        def check_lock(team, recs):
            with (team.dir / "lock").open("a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    blocked.append(True)
                else:
                    blocked.append(False)
                    fcntl.flock(lock, fcntl.LOCK_UN)

        with patch.object(cl, "itest_checkout", return_value=team.dir / "itest"), \
                patch.object(cl, "recheck_steps", return_value=([], [])), \
                patch.object(cl, "step_results", return_value=[]), \
                patch.object(cl, "apply_recheck_findings"), \
                patch.object(cl, "after_landing", side_effect=check_lock) as after, \
                patch.object(cl, "now", return_value="now"):
            cl.recheck_one(team, [row])
        assert cl.read_recheck(team) == [{**row, "done": "now"}]
        assert after.call_count == 1
        assert blocked == [True], "after_landing ran without the landing lock"


def test_recheck_runner_halted_does_not_process_pending():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        row = {"M": "pending"}
        (team.dir / "recheck.jsonl").write_text(json.dumps(row) + "\n")
        with patch.object(cl, "halted", return_value=True), patch.object(cl, "recheck_one") as one:
            cl.cmd_recheck_run(team, SimpleNamespace(once=True))
        one.assert_not_called()
        assert cl.read_recheck(team) == [row]


def test_recheck_runner_once_and_empty():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        rows = [{"time": "t1", "wo": "w1", "M": "first", "zones": ["A"], "overlapping": []},
                {"time": "t2", "wo": "w2", "M": "second", "zones": ["A"], "overlapping": []}]
        with patch.object(cl, "halted", return_value=False), patch.object(cl, "read_recheck", return_value=rows, create=True), \
                patch.object(cl, "git", return_value=SimpleNamespace(returncode=0)), \
                patch.object(cl, "recheck_one", create=True) as one:
            cl.cmd_recheck_run(team, SimpleNamespace(once=True))
            one.assert_called_once_with(team, rows)
        with patch.object(cl, "halted", return_value=False), patch.object(cl, "read_recheck", return_value=[], create=True), \
                patch.object(cl, "recheck_one", create=True) as one:
            cl.cmd_recheck_run(team, SimpleNamespace(once=True))
            one.assert_not_called()


def test_recheck_runner_held_lock():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        (team.dir / "recheck.jsonl").write_text('{"M":"pending"}\n')
        output = io.StringIO()
        with (team.dir / "recheck-run.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.object(cl, "halted", return_value=False), \
                    patch.object(cl, "recheck_one") as one, contextlib.redirect_stdout(output):
                try:
                    result = cl.cmd_recheck_run(team, SimpleNamespace(once=True))
                except SystemExit as exc:
                    result = exc.code
                assert result in (None, 0)
                one.assert_not_called()
        assert "already running" in output.getvalue()
        assert cl.read_recheck(team) == [{"M": "pending"}]


def test_service_install_remove_all_three():
    with tempfile.TemporaryDirectory() as tmp, patch.object(Path, "home", return_value=Path(tmp)):
        team = make_team(Path(tmp))
        agents = Path(tmp) / "Library/LaunchAgents"
        agents.mkdir(parents=True)
        def launchctl(argv, **kwargs):
            return SimpleNamespace(returncode=113 if argv[1] == "print" else 0, stdout="", stderr="")

        with patch.object(cl.subprocess, "run", side_effect=launchctl) as run, patch.object(cl.time, "sleep"):
            cl.cmd_service(team, SimpleNamespace(action="install"))
            assert sorted(p.name for p in agents.iterdir()) == ["com.codeteam.codeteam-land.sample.plist", "com.codeteam.codeteam-recheck.sample.plist", "com.codeteam.codeteam-validate.sample.plist"]
            bootstrap = [c.args[0] for c in run.call_args_list if c.args[0][1] == "bootstrap"]
            assert len(bootstrap) == 3
            assert {Path(c[-1]).name for c in bootstrap} == {"com.codeteam.codeteam-land.sample.plist", "com.codeteam.codeteam-recheck.sample.plist", "com.codeteam.codeteam-validate.sample.plist"}
            run.reset_mock()
            cl.cmd_service(team, SimpleNamespace(action="remove"))
            bootouts = [c.args[0][-1] for c in run.call_args_list if c.args[0][1] == "bootout"]
            assert len(bootouts) == 3
            assert any(x.endswith("/com.codeteam.codeteam-land.sample") for x in bootouts)
            assert any(x.endswith("/com.codeteam.codeteam-recheck.sample") for x in bootouts)
            assert any(x.endswith("/com.codeteam.codeteam-validate.sample") for x in bootouts)
            assert list(agents.iterdir()) == []


failed = 0
for test in [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)
             and (len(sys.argv) == 1 or k in sys.argv[1:])]:
    try:
        test()
        print(f"  PASS {test.__name__}")
    except (Exception, SystemExit) as exc:
        failed += 1
        print(f"  FAIL {test.__name__}: {type(exc).__name__}: {exc}")
print(f"{failed} failed" if failed else "all passed")
sys.exit(1 if failed else 0)
