#!/usr/bin/env -S python3 -u
"""Isolated contracts for landing rechecks and commit evidence."""
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
from unittest.mock import Mock, call, patch

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


def test_hang_examples():
    assert cl.hang_settings({}) == {"CODETEAM_HANG_WINDOW": "600", "CODETEAM_HANG_CPU_PCT": "1"}
    assert cl.hang_settings({"hang_min": 7, "hang_cpu_pct": 3}) == {"CODETEAM_HANG_WINDOW": "420", "CODETEAM_HANG_CPU_PCT": "3"}
    assert cl.hang_settings({"hang_min": 0.5}) == {"CODETEAM_HANG_WINDOW": "30", "CODETEAM_HANG_CPU_PCT": "1"}
    assert cl.hang_settings({"hang_min": 2.5, "hang_cpu_pct": 0.5}) == {"CODETEAM_HANG_WINDOW": "150", "CODETEAM_HANG_CPU_PCT": "0.5"}


def test_environment_hang_window():
    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
        env = cl.team_env(make_team(Path(tmp)), "integration")
    assert env["CODETEAM_HANG_WINDOW"] == "600"
    assert "CODETEAM_HANG_MIN" not in env


def test_explicit_env_hang_settings_are_kept():
    team = SimpleNamespace(root=Path("root"), dir=Path("land"), manifest=Path("team.toml"), cfg={"hang_min": 7},
                           m={"env": {"CODETEAM_HANG_WINDOW": "2", "CODETEAM_HANG_CPU_PCT": "4"}})
    with patch.dict(os.environ, {"CODETEAM_HANG_WINDOW": "900"}, clear=True):
        env = cl.team_env(team, "unit")
    assert (env["CODETEAM_HANG_WINDOW"], env["CODETEAM_HANG_CPU_PCT"]) == ("2", "4")
    team.m = {"env": {"CODETEAM_HANG_CPU_PCT": "4"}}
    with patch.dict(os.environ, {"CODETEAM_HANG_WINDOW": "900"}, clear=True):
        env = cl.team_env(team, "unit")
    assert (env["CODETEAM_HANG_WINDOW"], env["CODETEAM_HANG_CPU_PCT"]) == ("420", "4")


def test_hung_full_line_with_failure():
    with patch.object(cl, "records_pass", return_value=False):
        assert cl.step_outcome(1, "zone-test: HUNG: no output for 600 s; stopped the run and every process under it") == "HUNG"


def test_hung_full_line_with_success_and_passing_records():
    with patch.object(cl, "records_pass", return_value=True):
        assert cl.step_outcome(0, "  zone-test: HUNG: no output for 600 s; stopped the run and every process under it  ") == "HUNG"


def test_hung_bare_and_midline_and_failure():
    with patch.object(cl, "records_pass", return_value=False):
        assert cl.step_outcome(1, "zone-test: HUNG") == "HUNG"
        assert cl.step_outcome(0, "prefix zone-test: HUNG suffix") == "PASS"
        assert cl.step_outcome(1, "no marker") == "FAIL"


def test_units_pass_codes():
    assert cl.units_pass([]) is True
    assert cl.units_pass([0, 0]) is True
    assert cl.units_pass([0, 1]) is False
    assert cl.units_pass([0, 2]) is False


def test_current_units_unknown_keys():
    with patch.object(cl, "unit_step_keys", return_value=None), patch.object(cl, "commit_record", create=True) as record:
        assert cl.current_units(Mock(), Path("tree"), "z") is False
        record.assert_not_called()


def test_current_units_passes_each_key_at_head():
    tree = Path("tree")
    with patch.object(cl, "unit_step_keys", return_value=["one A owns=", "lane z"]), \
            patch.object(cl, "out", return_value="abc123") as out, \
            patch.object(cl, "commit_record", return_value=0, create=True) as record, \
            patch.object(cl, "zone_tool", return_value=SimpleNamespace(snapshot=Mock(), code_hash=Mock(), record_current=Mock(return_value=False))):
        assert cl.current_units(Mock(), tree, "z") is True
        out.assert_called_once_with(tree, "rev-parse", "HEAD")
        assert record.call_args_list == [call(tree, "abc123", "one A owns="), call(tree, "abc123", "lane z")]


def test_current_units_rejects_failed_or_missing():
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp)
        (tree / ".test-record-a.json").write_text(json.dumps({"result": "PASS", "key": "one A owns="}))
        (tree / ".test-record-b.json").write_text(json.dumps({"result": "PASS", "key": "lane z"}))
        for code in (1, 2):
            zt = SimpleNamespace(snapshot=Mock(), code_hash=Mock(), record_current=Mock(return_value=True))
            with patch.object(cl, "unit_step_keys", return_value=["one A owns=", "lane z"]), \
                    patch.object(cl, "out", return_value="abc123"), \
                    patch.object(cl, "commit_record", side_effect=[0, code], create=True), \
                    patch.object(cl, "zone_tool", return_value=zt):
                assert cl.current_units(Mock(), tree, "z") is False


def test_commit_record_command():
    tree = Path("tree")
    with patch.object(cl.subprocess, "run", return_value=SimpleNamespace(returncode=2)) as run:
        assert cl.commit_record(tree, "abc123", "one A owns=") == 2
    assert run.call_args.args[0] == [cl.HERE / "zone-tool", "commit-record", "abc123", "--key", "one A owns="]
    assert run.call_args.kwargs["cwd"] == tree


def test_pending_recheck():
    assert cl.pending_recheck([{"done": "y"}, {"M": "first"}, {"M": "second"}]) == 1
    assert cl.pending_recheck([{"done": "y"}]) is None
    assert cl.pending_recheck([]) is None


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


def test_itest_checkout_present_keeps_outputs():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        tree = team.dir / "itest"
        tree.mkdir()
        (tree / "build-output").write_text("keep")
        with patch.object(cl, "git", return_value=SimpleNamespace(returncode=0)) as git:
            assert cl.itest_checkout(team, "merge2") == tree
        git.assert_called_once_with(tree, "checkout", "-q", "--detach", "merge2", check=False)
        assert (tree / "build-output").read_text() == "keep"


def test_recheck_steps_only_type_check_and_integration():
    team, tree = Mock(), Path("tree")
    team.c.side_effect = lambda key, default: default
    with patch.object(cl, "compile_steps", return_value=[("compile A (a)", "check"), ("repo gates", "gates")]) as compile_, \
            patch.object(cl, "zone_tests", side_effect=[[('tests A', 'a')], [('tests B', 'b')]]) as tests, \
            patch.object(cl, "repo_integration_steps", return_value=[('integration tests (tests/integration)', 'repo')], create=True):
        assert cl.recheck_steps(team, tree, ["A", "B"]) == ([('compile A (a)', 'check')],
            [('tests A', 'a'), ('tests B', 'b'), ('integration tests (tests/integration)', 'repo')])
    compile_.assert_called_once_with(team, tree, ["A", "B"])
    assert tests.call_args_list == [call(team, tree, "A", "land", group="integration"), call(team, tree, "B", "land", group="integration")]


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


def test_run_steps_line_format():
    results = [{"name": "tests A", "outcome": "HUNG", "seconds": 4.0, "tail": ["bad", "zone-test: HUNG"]}]
    job = Mock(returncode=1)
    job.communicate.return_value = ("bad\nzone-test: HUNG\n",)
    with patch.object(cl, "step_results", return_value=results, create=True), \
            patch.object(cl.subprocess, "Popen", return_value=job), patch.object(cl.time, "time", side_effect=[0, 4]):
        assert cl.run_steps("tree", [("tests A", "a")], {}) == (False, ["HUNG tests A (4 s)", "  | bad", "  | zone-test: HUNG"])


def test_integration_result_exact():
    row = {"time": "old", "M": "merge", "wo": "work", "overlapping": ["other"], "zones": ["A"]}
    steps = [{"name": "type check", "outcome": "PASS", "seconds": 1.24, "tail": []},
             {"name": "tests A", "outcome": "HUNG", "seconds": 3.76, "tail": ["x"]}]
    assert cl.integration_result(row, steps, "now") == {"time": "now", "M": "merge", "wo": "work", "overlapping": ["other"],
        "zones": ["A"], "tests": [{"name": "type check", "result": "pass", "seconds": 1.2},
                                    {"name": "tests A", "result": "hung", "seconds": 3.8}]}


def test_recheck_findings_transitions():
    tests = [{"name": "new", "result": "fail"}, {"name": "old", "result": "hung"},
             {"name": "fixed", "result": "pass"}, {"name": "new", "result": "fail"}, {"name": "old", "result": "fail"}]
    fixes = [{"id": "f#1", "test": "old"}, {"id": "f#2", "test": "fixed"}, {"id": "f#3", "test": "absent"}]
    assert cl.recheck_findings(tests, fixes) == {"open": ["new"], "add": ["f#1"], "close": ["f#2"]}


def test_recheck_one_open_add_close():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        rec = {"wo": "work", "zone": "A", "feature": "feature", "fixes": ["prior#1"]}
        (team.dir / "wo" / "work.landed.json").write_text(json.dumps(rec))
        rows = [{"M": m, "wo": "work", "overlapping": ["other"], "zones": ["A"]} for m in ("merge11111111", "merge22222222", "merge33333333")]
        path = team.dir / "recheck.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        with patch.object(cl, "itest_checkout", return_value=team.dir / "itest", create=True), \
                patch.object(cl, "recheck_steps", return_value=([("type check", "check")], [("tests A", "test")]), create=True), \
                patch.object(cl, "step_results", side_effect=[
                    [{"name": "type check", "outcome": "PASS", "seconds": 1, "tail": []}],
                    [{"name": "tests A", "outcome": "FAIL", "seconds": 2, "tail": []}],
                    [{"name": "type check", "outcome": "PASS", "seconds": 1, "tail": []}],
                    [{"name": "tests A", "outcome": "FAIL", "seconds": 2, "tail": []}],
                    [{"name": "type check", "outcome": "PASS", "seconds": 1, "tail": []}],
                    [{"name": "tests A", "outcome": "PASS", "seconds": 2, "tail": []}]], create=True), \
                patch.object(cl, "after_landing") as after, patch.object(cl, "now", return_value="now"):
            cl.recheck_one(team, rows[0])
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
            cl.recheck_one(team, rows[1])
            [finding] = cl.load_findings(team, "feature")
            assert finding["Ms"] == ["merge11111111", "merge22222222"] and team.notify.call_count == 1
            cl.recheck_one(team, rows[2])
            assert cl.find_finding(team, "feature#1")["state"] == "closed"
            cl.update_finding(team, "feature#1", reason="verified")
            assert cl.find_finding(team, "feature#1")["reason"] == "verified"


def test_recheck_close_records_full_closing_commit():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        finding = {"id": "feat#1", "state": "open", "by": "recheck", "test": "a", "Ms": ["11111111111111111111"]}
        (team.dir / "findings").mkdir(exist_ok=True)
        cl.save_findings(team, "feat", [finding])
        cl.apply_recheck_findings(team, {"M": "abcdef0123456789abcd"}, {}, [{"name": "a", "result": "pass"}], "t2")
        finding = cl.find_finding(team, "feat#1")
        assert finding.get("closed_at") == "abcdef0123456789abcd"
        assert (finding["state"], finding["closed"], finding["fixed_by"], finding["reason"]) == (
            "closed", "t2", None, "passes at M abcdef0123")


def test_recheck_one_compile_failure_skips_tests():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        row = {"M": "merge", "wo": "work", "overlapping": [], "zones": ["A"]}
        (team.dir / "wo" / "work.landed.json").write_text(json.dumps({"wo": "work", "zone": "A"}))
        (team.dir / "recheck.jsonl").write_text(json.dumps(row) + "\n")
        with patch.object(cl, "itest_checkout", return_value=team.dir / "itest", create=True), \
                patch.object(cl, "recheck_steps", return_value=([("type check", "check")], [("tests A", "test")]), create=True), \
                patch.object(cl, "step_results", return_value=[{"name": "type check", "outcome": "FAIL", "seconds": 1, "tail": []}], create=True) as steps, \
                patch.object(cl, "after_landing"), patch.object(cl, "now", return_value="now"):
            result = cl.recheck_one(team, row)
        assert steps.call_count == 1
        assert result["tests"] == [{"name": "type check", "result": "fail", "seconds": 1.0}]


def test_recheck_one_orc_notifies_orchestrator():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        row = {"M": "merge", "wo": "work", "overlapping": [], "zones": ["orc"]}
        (team.dir / "wo" / "work.landed.json").write_text(json.dumps({"wo": "work", "zone": "orc"}))
        (team.dir / "recheck.jsonl").write_text(json.dumps(row) + "\n")
        with patch.object(cl, "itest_checkout", return_value=team.dir / "itest", create=True), \
                patch.object(cl, "recheck_steps", return_value=([], [("tests orc", "test")]), create=True), \
                patch.object(cl, "step_results", return_value=[{"name": "tests orc", "outcome": "FAIL", "seconds": 1, "tail": []}], create=True), \
                patch.object(cl, "after_landing"), patch.object(cl, "now", return_value="now"):
            cl.recheck_one(team, row)
        assert team.notify.call_args.args[0:2] == ("Skippy", "REQUEST")


def test_recheck_checkout_failure_records_notifies_completes_and_hands_off_set():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        row = {"M": "0123456789abcdef", "wo": "work-a", "set": ["work-a", "work-b"],
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
            result = cl.recheck_one(team, row)
        expected = {"time": "now", "M": "0123456789abcdef", "wo": "work-a", "set": ["work-a", "work-b"],
                    "overlapping": ["prior"], "zones": ["A"], "tests": [], "checkout": "failed", "error": "checkout refused"}
        assert result == expected
        assert [json.loads(line) for line in (team.dir / "integration-results.jsonl").read_text().splitlines()] == [expected]
        assert cl.read_recheck(team) == [{**row, "done": "now"}]
        team.notify.assert_called_once()
        to, kind, text = team.notify.call_args.args
        assert (to, kind) == ("Skippy", "NOTE")
        assert all(s in text for s in ("0123456789", "work-a", "work-b", "checkout refused"))
        after.assert_called_once_with(team, recs)
        steps.assert_not_called()
        findings.assert_not_called()


def test_recheck_findings_exception_keeps_result_and_marks_done():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        team.log = Mock()
        row = {"M": "merge", "wo": "work", "overlapping": [], "zones": ["A"]}
        (team.dir / "recheck.jsonl").write_text(json.dumps(row) + "\n")
        (team.dir / "wo" / "work.landed.json").write_text(json.dumps({"wo": "work", "zone": "A"}))
        with patch.object(cl, "itest_checkout", return_value=team.dir / "itest"), \
                patch.object(cl, "recheck_steps", return_value=([], [])), \
                patch.object(cl, "step_results", return_value=[]), \
                patch.object(cl, "apply_recheck_findings", side_effect=ValueError("bad finding")), \
                patch.object(cl, "after_landing"), patch.object(cl, "now", return_value="now"):
            result = cl.recheck_one(team, row)
        assert [json.loads(line) for line in (team.dir / "integration-results.jsonl").read_text().splitlines()] == [
            {"time": "now", "M": "merge", "wo": "work", "overlapping": [], "zones": ["A"], "tests": []}]
        assert result["M"] == "merge"
        team.log.assert_called_once_with({"time": "now", "wos": ["work"], "recheck_findings_error": "ValueError: bad finding"})
        assert cl.read_recheck(team) == [{**row, "done": "now"}]


def test_recheck_after_landing_holds_land_lock():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        row = {"M": "merge", "wo": "work", "overlapping": [], "zones": ["A"]}
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
            cl.recheck_one(team, row)
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
        rows = [{"wo": "w1", "M": "first"}, {"wo": "w2", "M": "second"}]
        with patch.object(cl, "halted", return_value=False), patch.object(cl, "read_recheck", return_value=rows, create=True), \
                patch.object(cl, "recheck_one", create=True) as one:
            cl.cmd_recheck_run(team, SimpleNamespace(once=True))
            one.assert_called_once_with(team, rows[0])
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


def test_service_jobs_and_plists():
    with tempfile.TemporaryDirectory() as tmp, patch.object(Path, "home", return_value=Path(tmp)):
        team = make_team(Path(tmp))
        jobs = cl.service_jobs(team)
        assert jobs == [("com.codeteam.codeteam-land.sample", "queue-run", Path(tmp) / "Library/LaunchAgents/com.codeteam.codeteam-land.sample.plist", team.dir / "queue-run.log"),
                        ("com.codeteam.codeteam-recheck.sample", "recheck-run", Path(tmp) / "Library/LaunchAgents/com.codeteam.codeteam-recheck.sample.plist", team.dir / "recheck-run.log"),
                        ("com.codeteam.codeteam-validate.sample", "validate-run", Path(tmp) / "Library/LaunchAgents/com.codeteam.codeteam-validate.sample.plist", team.dir / "validate-run.log")]
        for label, subcommand, _, log in jobs:
            text = cl.service_plist(team, label, subcommand, log)
            for value in (label, subcommand, "KeepAlive", "RunAtLoad", "ProcessType", "Interactive"):
                assert value in text


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


def test_service_status_reports_all_three_jobs():
    with tempfile.TemporaryDirectory() as tmp, patch.object(Path, "home", return_value=Path(tmp)):
        team = make_team(Path(tmp))
        output = io.StringIO()
        with patch.object(cl.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="state = running\n")) as run, \
                patch.object(cl, "halted", return_value=False), contextlib.redirect_stdout(output):
            cl.cmd_service(team, SimpleNamespace(action="status"))
        assert output.getvalue().splitlines() == ["com.codeteam.codeteam-land.sample: state = running",
                                                  "com.codeteam.codeteam-recheck.sample: state = running",
                                                  "com.codeteam.codeteam-validate.sample: state = running"]
        assert len(run.call_args_list) == 3
        assert [c.args[0][-1].rsplit("/", 1)[-1] for c in run.call_args_list] == [
            "com.codeteam.codeteam-land.sample", "com.codeteam.codeteam-recheck.sample", "com.codeteam.codeteam-validate.sample"]
        assert all(c.args[0][:2] == ["launchctl", "print"] for c in run.call_args_list)


def test_parser_recheck_run():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        with patch.object(cl, "cmd_recheck_run", create=True) as run:
            cl.main([str(team.manifest), "recheck-run"])
            assert run.call_args.args[1].once is False
            cl.main([str(team.manifest), "recheck-run", "--once"])
            assert run.call_args.args[1].once is True
            assert run.call_count == 2


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
