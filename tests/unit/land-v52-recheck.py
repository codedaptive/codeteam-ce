#!/usr/bin/env -S python3 -u
"""Isolated contracts for landing rechecks and commit evidence: the unit tests (rule 11); processes, git and the
paths that take a lock are faked. The tests on real boundaries are in tests/integration/land-v52-recheck.py."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import plistlib
import subprocess
import sys
import tempfile
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
        assert cl.recheck_steps(team, tree, ["A", "B"], ["tools/p/a.swift"]) == ([('compile A (a)', 'check')],
            [('tests A', 'a'), ('tests B', 'b'), ('integration tests (tests/integration)', 'repo')])
    compile_.assert_called_once_with(team, tree, ["A", "B"])
    # the landing's files reach each zone's tests, for the test roots below a plain owned folder
    assert tests.call_args_list == [call(team, tree, "A", "land", group="integration", files=["tools/p/a.swift"]),
                                    call(team, tree, "B", "land", group="integration", files=["tools/p/a.swift"])]


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
                                    {"name": "tests A", "result": "hung", "seconds": 3.8, "tail": ["x"]}]}


def test_recheck_findings_transitions():
    tests = [{"name": "new", "result": "fail"}, {"name": "old", "result": "hung"},
             {"name": "fixed", "result": "pass"}, {"name": "new", "result": "fail"}, {"name": "old", "result": "fail"}]
    fixes = [{"id": "f#1", "test": "old"}, {"id": "f#2", "test": "fixed"}, {"id": "f#3", "test": "absent"}]
    assert cl.recheck_findings(tests, fixes) == {"open": ["new"], "add": ["f#1"], "close": ["f#2"]}


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


def test_service_plist_path_uses_checkout_and_home():
    with tempfile.TemporaryDirectory() as tmp, patch.object(Path, "home", return_value=Path(tmp)):
        team = make_team(Path(tmp))
        text = cl.service_plist(team, "sample", "queue-run", Path(tmp) / "service.log")
        got = plistlib.loads(text.encode())["EnvironmentVariables"]["PATH"]
        want = (f"{ROOT / 'bin'}:{ROOT / 'v2' / 'bin'}:{Path(tmp) / '.cargo' / 'bin'}:"
                "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin")
        assert got == want, f"got {got!r}, expected {want!r}"


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
