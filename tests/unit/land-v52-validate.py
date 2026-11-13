#!/usr/bin/env -S python3 -u
"""Isolated contracts for Stage 6 validation."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import queue
import re
import subprocess
import tempfile
import threading
import traceback
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

# Restart markers and stage admissions live beside the queue; keep them out of the checkout.
os.environ["CODETEAM_QUEUE_DIR"] = str(Path(tempfile.mkdtemp(prefix="land-queue-")) / "queue")

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_validate", str(ROOT / "bin" / "codeteam-land"))
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
    team.zones = {"a": ["src/a"], "b": ["src/b"]}
    team.notify = Mock()
    return team








def test_stage6_target_runs_with_fix_open():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        with cl.FindingsLock(team):
            cl.save_findings(team, "validation", [{"id": "validation#1", "state": "open", "test": "a",
                                                   "by": "validation", "commits": ["older"]}])
        with patch.object(cl, "read_recheck", return_value=[]), \
                patch.object(cl, "out", return_value="abcdef0123456789\nolder\n"):
            assert cl.stage6_target(team) == "abcdef0123456789"


def test_stage6_target_returns_done_ancestor_of_pending_landing():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        rows = [{"M": "L1", "done": "yes"}, {"M": "L2"}]
        def git(repo, *args, **kwargs):
            ancestor = args[-2:] in (("L1", "L1"), ("L1", "L2"), ("L2", "L2"))
            return SimpleNamespace(returncode=0 if ancestor else 1, stdout="", stderr="")
        with patch.object(cl, "read_recheck", return_value=rows), \
                patch.object(cl, "out", return_value="L2\nL1\n"), patch.object(cl, "git", side_effect=git):
            assert cl.stage6_target(team) == "L1", "pending L2 must not starve completed L1"


def test_last_validated_skips_error_and_toolchain():
    rows = [{"commit": "a", "result": "pass"}, {"commit": "b", "result": "hung"},
            {"commit": "c", "result": "error"}, {"commit": "d", "result": "toolchain"}]
    assert cl.last_validated(rows) == "b"
    assert cl.last_validated(rows[2:]) is None


def test_validate_due_skip_last_and_retry_error():
    rows = [{"commit": "a", "result": "pass", "time": "1970-01-01T00:00:00+00:00"},
            {"commit": "b", "result": "error", "time": "1970-01-01T00:01:40+00:00"}]
    assert cl.validate_due(rows, None, 110, 60) is False
    assert cl.validate_due(rows, "a", 110, 60) is False
    assert cl.validate_due(rows, "b", 110, 60) is False
    assert cl.validate_due(rows, "b", 161, 60) is True


def test_default_tier_is_validate_suite_with_step_log():
    with tempfile.TemporaryDirectory() as tmp:
        a = cl.alpha_cfg(make_team(Path(tmp)))
        assert a["suite"].split()[-1] == "validate-suite"
        assert a["steps"] is True


def test_validate_suite_selects_validation_steps_without_compile():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        with patch.object(cl, "zone_tests", side_effect=lambda t, tree, z, cls, group: [(z, group)]) as zones, \
             patch.object(cl, "repo_test_steps", return_value=[("repo", "validation")]) as repo, \
             patch.object(cl, "compile_steps") as compile_steps, \
             patch.object(cl, "run_steps", return_value=(True, ["PASS suite (1 s)"])) as run, \
             contextlib.redirect_stdout(io.StringIO()):
            try:
                cl.cmd_validate_suite(team, SimpleNamespace())
            except SystemExit as ex:
                assert ex.code == 0
        assert [c.args[2] for c in zones.call_args_list] == ["a", "b"]
        assert all(c.args[3] == "full" and c.kwargs["group"] == "validation" for c in zones.call_args_list)
        assert repo.call_args.args[2:4] == ("validation", "full")
        assert repo.call_args.args[1] == "tests/validation"
        assert run.call_args.args[1] == [("a", "validation"), ("b", "validation"), ("repo", "validation")]
        assert run.call_args.args[2]["CODETEAM_TEST_GROUP"] == "validation"
        compile_steps.assert_not_called()


def test_validate_suite_flushes_each_completion_and_preserves_summary():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        clock = [10]
        events = []
        pending = []
        summaries = []
        run_steps = cl.run_steps

        class Output(io.StringIO):
            def flush(self):
                events.append(("flush", self.getvalue()))

        def submit(finish, job):
            future = Future()
            pending.append((future, finish, job))
            return future

        def completed(futures):
            assert futures == [job[0] for job in pending]
            for index in (1, 2, 0):
                future, finish, job = pending[index]
                future.set_result(finish(job))
                yield future

        def process(command, **kwargs):
            end, code, text = {"a": (17, 0, "ok"), "b": (12, 1, "bad"),
                               "repo": (14, 124, "stalled")}[command]
            def communicate():
                clock[0] = end
                events.append(("finished", command))
                return (text,)
            return SimpleNamespace(returncode=code, communicate=communicate)

        def capture_summary(*args, **kwargs):
            result = run_steps(*args, **kwargs)
            summaries.append(result)
            return result

        output = Output()
        with patch.object(cl, "zone_tests", side_effect=lambda t, tree, z, cls, group: [(z, z)]), \
                patch.object(cl, "repo_test_steps", return_value=[("repo", "repo")]), \
                patch.object(cl, "team_env", return_value={}), \
                patch.object(cl.subprocess, "Popen", side_effect=process), \
                patch.object(cl, "ThreadPoolExecutor") as executor, \
                patch.object(cl, "as_completed", side_effect=completed), \
                patch.object(cl.time, "time", side_effect=lambda: clock[0]), \
                patch.object(cl, "run_steps", side_effect=capture_summary), \
                contextlib.redirect_stdout(output):
            executor.return_value.__enter__.return_value.submit.side_effect = submit
            try:
                cl.cmd_validate_suite(team, SimpleNamespace())
            except SystemExit as ex:
                assert ex.code == 1
            else:
                raise AssertionError("a failed validation suite must exit nonzero")
        assert events == [
            ("finished", "b"), ("flush", "FAIL b (2 s)\n  | bad\n"),
            ("finished", "repo"), ("flush", "FAIL b (2 s)\n  | bad\nHUNG repo (4 s)\n  | stalled\n"),
            ("finished", "a"),
            ("flush", "FAIL b (2 s)\n  | bad\nHUNG repo (4 s)\n  | stalled\nPASS a (7 s)\n")]
        assert summaries == [(False, ["PASS a (7 s)", "FAIL b (2 s)", "  | bad",
                                     "HUNG repo (4 s)", "  | stalled"])]
        assert output.getvalue() == "FAIL b (2 s)\n  | bad\nHUNG repo (4 s)\n  | stalled\nPASS a (7 s)\n"


def test_validate_suite_heartbeat_every_quarter_window_while_steps_pending():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        clock = [100]
        flushed = queue.Queue()
        ticks = queue.Queue()
        waits = []
        releases = {"a": threading.Event(), "repo": threading.Event()}
        started = queue.Queue()
        exits = []

        class Output(io.StringIO):
            def flush(self):
                flushed.put(self.getvalue())

        class FakeStop:
            """Each wait returns when the test ticks it, after moving the fake clock by the interval asked for."""
            stopped = False

            def wait(self, timeout):
                waits.append(timeout)
                ticks.get()
                clock[0] += timeout
                return self.stopped

            def set(self):
                self.stopped = True
                ticks.put(None)

        def process(command, **kwargs):
            started.put(command)

            def communicate():
                releases[command].wait()
                return ("ok",)
            return SimpleNamespace(returncode=0, communicate=communicate)

        real = cl.run_with_heartbeat

        def suite():
            try:
                cl.cmd_validate_suite(team, SimpleNamespace())
            except SystemExit as ex:
                exits.append(ex.code)

        def step(event=None):
            if event is not None:
                event.set()
            return flushed.get(timeout=10)       # a guard against a broken heartbeat; never reached when it works

        output = Output()
        with patch.dict(cl.os.environ, {"CODETEAM_HANG_WINDOW": "8"}), \
                patch.object(cl, "zone_tests", side_effect=lambda t, tree, z, cls, group: [("tests a (src/a)", "a")] if z == "a" else []), \
                patch.object(cl, "repo_test_steps", return_value=[("validation tests (tests/validation)", "repo")]), \
                patch.object(cl, "team_env", return_value={}), \
                patch.object(cl.subprocess, "Popen", side_effect=process), \
                patch.object(cl.time, "time", side_effect=lambda: clock[0]), \
                patch.object(cl.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(cl, "run_with_heartbeat",
                             side_effect=lambda tree, steps, env, interval, stop: real(tree, steps, env, interval, FakeStop())), \
                contextlib.redirect_stdout(output):
            worker = threading.Thread(target=suite)
            worker.start()
            # Both steps start at clock 100 before the first tick moves it.
            assert sorted([started.get(timeout=10), started.get(timeout=10)]) == ["a", "repo"]
            ticks.put(None)
            first = step()
            ticks.put(None)
            second = step()
            after_repo = step(releases["repo"])
            ticks.put(None)
            third = step()
            last = step(releases["a"])
            worker.join()
        both = "waiting: tests a (src/a), validation tests (tests/validation)"
        assert first == f"{both} (2 s)\n"
        assert second == f"{both} (2 s)\n{both} (4 s)\n"
        assert after_repo == second + "PASS validation tests (tests/validation) (4 s)\n"
        assert third == after_repo + "waiting: tests a (src/a) (6 s)\n"
        assert last == third + "PASS tests a (src/a) (6 s)\n"
        assert output.getvalue() == last
        assert flushed.empty()
        assert waits == [2, 2, 2, 2]
        assert exits == [0]
        assert not any(re.fullmatch(r"(PASS|FAIL|HUNG) (.+) \((\d+) s\)", line)
                       for line in output.getvalue().splitlines() if line.startswith("waiting:"))
        assert cl.validation_tests({"result": "pass", "seconds": 6}, output.getvalue(), []) == [
            {"name": "validation tests (tests/validation)", "result": "pass", "seconds": 4},
            {"name": "tests a (src/a)", "result": "pass", "seconds": 6}]


def test_remote_group_and_hang_settings_and_hung_result():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        team.cfg.update({"hang_min": 7, "hang_cpu_pct": 3})
        a = {"host": "fake", "path": "/clone", "suite": "suite", "toolchain": ["true"]}
        response = SimpleNamespace(stdout='{"hash":"abc","result":"hung","seconds":12,"tail":""}\n', stderr="", returncode=0)
        with patch.object(cl, "ssh", return_value=response) as ssh, patch.object(cl, "toolchain_fp", return_value="fp"):
            result = cl.run_land_check(team, a, "abc", "validation")
        command = ssh.call_args.args[1]
        assert "CODETEAM_TEST_GROUP=validation" in command
        # A repo Makefile reads GROUP (e.g. a product's test script): Stage 6 sets it too, as Stage 2 does. A whole
        # word: "GROUP=validation" is also a substring of CODETEAM_TEST_GROUP=validation.
        assert "GROUP=validation" in command.split()
        assert "CODETEAM_HANG_WINDOW=420" in command
        assert "CODETEAM_HANG_CPU_PCT=3" in command
        assert result["result"] == "hung"


def test_remote_script_preserves_ignored_files_and_logs_while_running():
    assert "git clean -q -fd " in cl.REMOTE_CHECK
    # The one clean of ignored files is limited to Python's bytecode caches.
    script = cl.REMOTE_CHECK
    assert script.count("git clean -q -fdx") == 1, script
    limited = script[script.index("git clean -q -fdx"):].split("||")[0]
    assert limited.rstrip().endswith("-- ':(glob)**/__pycache__/' ':(glob)**/*.pyc'"), limited
    assert "$build" in limited and "$keep" in limited and "-e DerivedData" in limited
    assert script.index("export PYTHONDONTWRITEBYTECODE=1") < script.index('sh -c "$suite"')
    assert "hung" in cl.REMOTE_CHECK
    assert "land-check-logs" in cl.REMOTE_CHECK
    assert cl.REMOTE_CHECK.index("land-check-logs") < cl.REMOTE_CHECK.index('sh -c "$suite"')


def test_validation_steps_log_parses_all_outcomes():
    log = "PASS tests a (3 s)\nFAIL tests b (7 s)\nHUNG repo (12 s)\nnoise\n"
    assert cl.validation_tests({"result": "hung", "seconds": 22}, log, []) == [
        {"name": "tests a", "result": "pass", "seconds": 3},
        {"name": "tests b", "result": "fail", "seconds": 7},
        {"name": "repo", "result": "hung", "seconds": 12}]


def test_validation_cut_off_step_adds_suite():
    assert cl.validation_tests({"result": "fail", "seconds": 4}, "PASS tests a (2 s)\n", []) == [
        {"name": "tests a", "result": "pass", "seconds": 2},
        {"name": "suite", "result": "fail", "seconds": 4}]


def test_validation_team_pass_closes_open_names():
    assert cl.validation_tests({"result": "pass", "seconds": 5}, None, ["a", "b"]) == [
        {"name": "suite", "result": "pass", "seconds": 5},
        {"name": "a", "result": "pass", "seconds": None},
        {"name": "b", "result": "pass", "seconds": None}]


def test_validation_failed_zones_uses_last_line():
    rows = cl.validation_tests({"result": "fail", "seconds": 9, "tail": "FAILED ZONES: old|FAILED ZONES: a b"}, None, ["a", "c"])
    assert rows == [{"name": "a", "result": "fail", "seconds": None},
                    {"name": "b", "result": "fail", "seconds": None},
                    {"name": "c", "result": "pass", "seconds": None}]


def test_validation_hung_failed_modules_also_records_suite():
    rows = cl.validation_tests({"result": "hung", "seconds": 20, "tail": "FAILED MODULES: a b"}, None, ["c"])
    assert rows == [{"name": "a", "result": "fail", "seconds": None},
                    {"name": "b", "result": "fail", "seconds": None},
                    {"name": "c", "result": "pass", "seconds": None},
                    {"name": "suite", "result": "hung", "seconds": 20}]


def test_validation_failure_without_names_is_suite():
    assert cl.validation_tests({"result": "fail", "seconds": 4, "tail": "failed"}, None, ["a"]) == [
        {"name": "suite", "result": "fail", "seconds": 4}]


def test_validation_zone_resolves_step_and_path():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        assert cl.validation_zone(team, "tests a (src/a)") == "a"
        assert cl.validation_zone(team, "src/b/test_x.py") == "b"
        assert cl.validation_zone(team, "suite") == "orc"
        assert cl.validation_zone(team, "tests/validation") == "orc"


def test_validation_zone_routes_bare_zone_name_to_its_owner():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        assert cl.validation_zone(team, "a") == "a"
        assert cl.validation_zone(team, "b") == "b"
        assert cl.validation_zone(team, "unknown") == "orc"


def test_df_free_gib_uses_available_kib():
    df = "Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/disk 209715200 104857600 78643200 58% /\n"
    assert cl.df_free_gib(df) == 75.0
    assert cl.df_free_gib("not df output") is None


def test_floor_clean_command_only_ignored_and_excludes_keep():
    import shlex
    command = cl.floor_clean_command("/clone", ["keep"])
    assert shlex.split(command) == ["cd", "/clone", "&&", "git", "clean", "-q", "-f", "-d", "-X", "-e", "!/.codegraph",
                                    "-e", "!/keep", "--", "."]


def test_stage4_does_not_close_validation_findings():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        finding = {"id": "validation#1", "by": "validation", "test": "tests a", "state": "open"}
        with patch.object(cl, "all_findings", return_value=[finding]), patch.object(cl, "update_finding") as update:
            cl.apply_recheck_findings(team, {"M": "abc"}, {}, [{"name": "tests a", "result": "pass"}], "now")
        update.assert_not_called()


def test_landing_bookkeeping_sends_no_pull_notice_or_validation_job():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        with patch.object(cl, "member_bookkeeping"), patch.object(cl, "after_landing"), patch.object(cl.subprocess, "Popen") as spawn:
            cl.landing_bookkeeping(team, [{"wo": "w", "reach": ["a"]}], [{"recheck": False, "hash": "abc"}])
        team.notify.assert_not_called()
        spawn.assert_not_called()


def test_service_jobs_includes_validation_runner():
    with tempfile.TemporaryDirectory() as tmp:
        jobs = cl.service_jobs(make_team(Path(tmp)))
        assert ("com.codeteam.codeteam-validate.sample", "validate-run") in [(label, cmd) for label, cmd, _, _ in jobs]


def assert_cli_rejects(name):
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        with patch.object(cl, "Team", return_value=team), contextlib.redirect_stderr(io.StringIO()):
            try:
                cl.main([str(team.manifest), name, "--help"])
            except SystemExit as ex:
                assert ex.code != 0, f"{name} is still accepted"
            else:
                raise AssertionError(f"{name} is still accepted")


def test_full_suite_cli_removed():
    assert_cli_rejects("full-suite")


def test_alpha_run_cli_removed():
    assert_cli_rejects("alpha-run")


def test_alpha_bisect_cli_accepts_hash_and_dispatches():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        with patch.object(cl, "Team", return_value=team), patch.object(cl, "cmd_alpha_bisect") as bisect:
            cl.main([str(team.manifest), "alpha-bisect", "red"])
        bisect.assert_called_once()
        assert bisect.call_args.args[0] is team
        assert bisect.call_args.args[1].hash == "red"


def bisect_team(root):
    team = make_team(root)
    (team.dir / "landed.log").write_text(
        '{"hash":"good","wos":["first"],"zone":"a"}\n'
        '{"promote":"good","to":"main"}\n'
        '{"hash":"middle","wos":["culprit"],"zone":"b"}\n'
        '{"hash":"red","wos":["last"],"zone":"a"}\n')
    (team.dir / "validation-results.jsonl").write_text(
        '{"commit":"good","result":"pass","tests":[{"name":"suite","result":"pass"}]}\n')
    # Stale full-run evidence must not make middle a good commit.
    (team.dir / "results.jsonl").write_text('{"hash":"middle","result":"pass"}\n')
    (team.dir / "green").write_text("middle\n")
    return team


def test_alpha_bisect_finds_culprit_from_validation_and_probes_write_no_rows():
    with tempfile.TemporaryDirectory() as tmp:
        team = bisect_team(Path(tmp))
        a = {"local": True}
        before = {name: (team.dir / name).read_bytes() for name in ("validation-results.jsonl", "results.jsonl")}
        with patch.object(cl, "alpha_cfg", return_value=a), \
                patch.object(cl, "check_at", return_value={"result": "fail"}) as probe, \
                patch.object(cl, "out", return_value="src/b/code.py"), patch.object(cl, "cmd_revert") as revert, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            cl.cmd_alpha_bisect(team, SimpleNamespace(hash="red"))
        assert [call.args for call in probe.call_args_list] == [
            (team, a, "middle", "validation"), (team, a, "middle", "validation")]
        assert all(not call.kwargs for call in probe.call_args_list)
        revert.assert_not_called()
        assert [call.args for call in team.notify.call_args_list] == [
            ("Skippy", "NOTE", "validation bisect: culprit (landed at middle, zone b) broke the validation suite."),
            ("Coord-b", "NOTE", "validation bisect: culprit (landed at middle) broke landing's validation suite.")]
        assert output.getvalue() == "culprit: culprit at middle (zone b)\n"
        assert (team.dir / "validation-results.jsonl").read_bytes() == before["validation-results.jsonl"]
        assert (team.dir / "results.jsonl").read_bytes() == before["results.jsonl"]


def test_alpha_bisect_docs_only_landing_is_not_blamed():
    with tempfile.TemporaryDirectory() as tmp:
        team = bisect_team(Path(tmp))
        with patch.object(cl, "alpha_cfg", return_value={"local": True}), \
                patch.object(cl, "check_at", return_value={"result": "fail"}) as probe, \
                patch.object(cl, "out", return_value="docs/guide.md"), patch.object(cl, "cmd_revert") as revert:
            cl.cmd_alpha_bisect(team, SimpleNamespace(hash="red"))
        assert probe.call_count == 1
        revert.assert_not_called()
        assert team.notify.call_args.args[:2] == ("Skippy", "NOTE")
        assert "docs-only landing: not blamed and not reverted" in team.notify.call_args.args[2]


def test_alpha_bisect_flaky_confirmation_is_not_reverted():
    with tempfile.TemporaryDirectory() as tmp:
        team = bisect_team(Path(tmp))
        with patch.object(cl, "alpha_cfg", return_value={"local": True}), \
                patch.object(cl, "check_at", side_effect=[{"result": "fail"}, {"result": "pass"}]), \
                patch.object(cl, "out", return_value="src/b/code.py"), patch.object(cl, "cmd_revert") as revert:
            cl.cmd_alpha_bisect(team, SimpleNamespace(hash="red"))
        revert.assert_not_called()
        assert "passed when run again: flaky, not reverted" in team.notify.call_args.args[2]


def test_alpha_bisect_checks_unvalidated_parent_before_reporting():
    with tempfile.TemporaryDirectory() as tmp:
        team = bisect_team(Path(tmp))
        with patch.object(cl, "alpha_cfg", return_value={"local": True}), \
                patch.object(cl, "check_at", side_effect=[{"result": "pass"}, {"result": "fail"}, {"result": "pass"}]) as probe, \
                patch.object(cl, "out", return_value="src/a/code.py"), patch.object(cl, "cmd_revert") as revert, \
                contextlib.redirect_stdout(io.StringIO()):
            cl.cmd_alpha_bisect(team, SimpleNamespace(hash="red"))
        assert [call.args[2:] for call in probe.call_args_list] == [
            ("middle", "validation"), ("red", "validation"), ("middle", "validation")]
        revert.assert_not_called()
        assert [call.args[:2] for call in team.notify.call_args_list] == [("Skippy", "NOTE"), ("Coord-a", "NOTE")]
        assert team.notify.call_args_list[0].args[2] == "validation bisect: last (landed at red, zone a) broke the validation suite."


def test_alpha_bisect_failing_parent_is_not_reverted():
    with tempfile.TemporaryDirectory() as tmp:
        team = bisect_team(Path(tmp))
        with patch.object(cl, "alpha_cfg", return_value={"local": True}), \
                patch.object(cl, "check_at", side_effect=[{"result": "pass"}, {"result": "fail"}, {"result": "fail"}]), \
                patch.object(cl, "out", return_value="src/a/code.py"), patch.object(cl, "cmd_revert") as revert:
            cl.cmd_alpha_bisect(team, SimpleNamespace(hash="red"))
        revert.assert_not_called()
        assert "parent middle fails too" in team.notify.call_args.args[2]
        assert "not reverted" in team.notify.call_args.args[2]


def test_alpha_bisect_uses_latest_validation_row_for_good_commits():
    with tempfile.TemporaryDirectory() as tmp:
        team = bisect_team(Path(tmp))
        with (team.dir / "validation-results.jsonl").open("a") as file:
            file.write('{"commit":"good","result":"fail","tests":[]}\n')
        with patch.object(cl, "alpha_cfg", return_value={"local": True}), \
                patch.object(cl, "check_at", side_effect=[{"result": "pass"}, {"result": "fail"},
                                                        {"result": "fail"}, {"result": "pass"}]) as probe, \
                patch.object(cl, "out", return_value="src/b/code.py"), patch.object(cl, "cmd_revert") as revert, \
                contextlib.redirect_stdout(io.StringIO()):
            cl.cmd_alpha_bisect(team, SimpleNamespace(hash="red"))
        assert [call.args[2] for call in probe.call_args_list] == ["good", "middle", "middle", "good"]
        revert.assert_not_called()
        assert team.notify.call_args_list[0].args == (
            "Skippy", "NOTE", "validation bisect: culprit (landed at middle, zone b) broke the validation suite.")


def test_stage6_target_needs_no_review_record():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        with patch.object(cl, "read_recheck", return_value=[]), patch.object(cl, "out", return_value="new\nold\n") as out:
            assert cl.stage6_target(team) == "new"
        out.assert_called_once_with(team.repo, "rev-list", "--first-parent", "landing")


def test_stage6_target_ignores_pending_review_records():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        (team.dir / "reviews" / "old.json").write_text(json.dumps({"state": "pending"}))
        with patch.object(cl, "read_recheck", return_value=[]), patch.object(cl, "out", return_value="new\nreviewed\nold\n"):
            assert cl.stage6_target(team) == "new"


def test_disk_check_below_floor_cleans_and_reports_after():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        a = {"host": "fake", "path": "/clone", "keep": ["keep"]}
        before = SimpleNamespace(returncode=0, stdout="Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/x 100000000 1 52428800 1% /\n", stderr="")
        after = SimpleNamespace(returncode=0, stdout="Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/x 100000000 1 73400320 1% /\n", stderr="")
        with patch.object(cl, "ssh", side_effect=[before, SimpleNamespace(returncode=0, stdout="", stderr=""), after]) as ssh:
            disk = cl.disk_check(team, a)
        assert disk == {"free_gib": 50.0, "floor_gib": 60, "cleaned": True, "free_after_gib": 70.0}
        assert "-X" in ssh.call_args_list[1].args[1]
        assert "-e '!/.codegraph'" in ssh.call_args_list[1].args[1]
        assert "-e '!/keep'" in ssh.call_args_list[1].args[1]


def test_disk_check_above_floor_does_not_clean():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        a = {"host": "fake", "path": "/clone"}
        df = SimpleNamespace(returncode=0, stdout="Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/x 100000000 1 73400320 1% /\n", stderr="")
        with patch.object(cl, "ssh", return_value=df) as ssh:
            assert cl.disk_check(team, a) == {"free_gib": 70.0, "floor_gib": 60, "cleaned": False}
        assert ssh.call_count == 1


def test_disk_check_failed_df_does_not_clean():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        with patch.object(cl, "ssh", return_value=SimpleNamespace(returncode=1, stdout="", stderr="df failed")) as ssh:
            assert "error" in cl.disk_check(team, {"host": "fake", "path": "/clone"})
        assert ssh.call_count == 1


def test_validation_findings_open_add_close_and_route():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        failed = [{"name": "tests a (src/a)", "result": "fail", "seconds": 2}]
        cl.apply_validation_findings(team, "1234567890aaaa", failed, "t1")
        path = team.dir / "findings" / "validation.json"
        items = json.loads(path.read_text())
        assert len(items) == 1
        assert (items[0]["id"], items[0]["by"], items[0]["zone"], items[0]["commits"], items[0]["state"]) == (
            "validation#1", "validation", "a", ["1234567890aaaa"], "open")
        recipient, kind, text = team.notify.call_args.args
        assert (recipient, kind) == ("Coord-a", "REQUEST")
        assert "FIX-FORWARD validation#1" in text and "--fixes validation#1" in text
        # A fix tree stays cut from integration and merges the failing landing
        # commit when the cause lives only on landing (Stage 4 step 3 was once read as forbidding it).
        assert "merge 1234567890 into the fix tree" in text
        team.notify.reset_mock()
        cl.apply_validation_findings(team, "bbbbbbbbbbcccc", failed, "t2")
        items = json.loads(path.read_text())
        assert items[0]["commits"] == ["1234567890aaaa", "bbbbbbbbbbcccc"]
        team.notify.assert_not_called()
        cl.apply_validation_findings(team, "ccccccccccdddd", [{"name": "tests a (src/a)", "result": "pass", "seconds": 1}], "t3")
        item = json.loads(path.read_text())[0]
        assert item["state"] == "closed"
        assert item["reason"] == "passes in validation at C cccccccccc"


def test_validation_close_records_full_closing_commit():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        cl.apply_validation_findings(team, "11111111111111111111", [{"name": "a", "result": "fail"}], "t1")
        cl.apply_validation_findings(team, "abcdef0123456789abcd", [{"name": "a", "result": "pass"}], "t2")
        finding = cl.find_finding(team, "validation#1")
        assert finding.get("closed_at") == "abcdef0123456789abcd"
        assert (finding["state"], finding["closed"], finding["fixed_by"], finding["reason"]) == (
            "closed", "t2", None, "passes in validation at C abcdef0123")


def test_validation_findings_orc_routes_to_orchestrator():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        cl.apply_validation_findings(team, "1234567890abc", [{"name": "suite", "result": "hung", "seconds": 2}], "now")
        assert team.notify.call_args.args[:2] == ("Skippy", "REQUEST")


def test_validate_one_writes_validation_record_not_old_results():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        a = {"host": "fake", "path": "/clone", "suite": "suite"}
        res = {"hash": "abc", "result": "pass", "seconds": 3, "time": "now", "disk": {"free_gib": 70, "floor_gib": 60, "cleaned": False}}
        with patch.object(cl, "check_at", return_value=res, create=True), patch.object(cl, "apply_validation_findings", create=True):
            row = cl.validate_one(team, a, "abc")
        assert row["commit"] == "abc" and row["result"] == "pass" and row["time"] == "now"
        assert row["disk"] == {"free_gib": 70, "floor_gib": 60, "cleaned": False}
        assert row["tests"] == [{"name": "suite", "result": "pass", "seconds": 3}]
        assert json.loads((team.dir / "validation-results.jsonl").read_text()) == row
        assert not (team.dir / "results.jsonl").exists()


def test_migrate_default_tier_runs_validation_and_records_result():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        with patch.object(cl, "v2_layout", return_value=("exchange", "", {}, [])), \
             patch.object(cl, "out", side_effect=[str(team.repo / ".git"), "abc"]), \
             patch.object(cl, "git", return_value=SimpleNamespace(returncode=0, stderr="")), \
             patch.object(cl, "ensure_land_check", return_value=None), \
             patch.object(cl, "run_land_check", return_value={"hash": "abc", "result": "pass", "seconds": 3}) as run, \
             contextlib.redirect_stdout(io.StringIO()):
            try:
                cl.cmd_migrate(team, SimpleNamespace(step="check"))
            except SystemExit as ex:
                assert ex.code == 0
        assert run.call_args.args[1]["suite"].split()[-1] == "validate-suite"
        assert run.call_args.args[3] == "validation"
        assert json.loads((team.dir / "results.jsonl").read_text())["result"] == "pass"


def test_stage6_target_returns_tip_and_due_skips_last_validated():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        (team.dir / "validation-results.jsonl").write_text(json.dumps({"commit": "last", "result": "pass"}) + "\n")
        with patch.object(cl, "read_recheck", return_value=[]), patch.object(cl, "out", return_value="last\nolder\n"):
            assert cl.stage6_target(team) == "last"
        assert cl.validate_due(cl.validation_rows(team), "last", 10, 1) is False


def test_validate_run_lock_refuses_second_runner():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        with patch.object(cl.fcntl, "flock", side_effect=BlockingIOError), \
             patch.object(cl, "halted") as halted, contextlib.redirect_stdout(io.StringIO()) as output:
            cl.cmd_validate_run(team, SimpleNamespace(once=True))
        assert "already running" in output.getvalue()
        halted.assert_not_called()


def test_validate_run_once_runs_one_due_target_without_sleep():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        a = {"local": True, "host": "local", "path": "/clone", "suite": "suite"}
        row = {"commit": "abc", "result": "fail", "tests": []}
        with patch.object(cl, "halted", return_value=False), \
             patch.object(cl, "stage6_target", return_value="abc", create=True), \
             patch.object(cl, "alpha_cfg", return_value=a), \
             patch.object(cl, "validate_due", return_value=True, create=True), \
             patch.object(cl, "validate_one", return_value=row, create=True) as validate, \
             patch.object(cl.time, "sleep") as sleep:
            assert cl.cmd_validate_run(team, SimpleNamespace(once=True)) == row
        validate.assert_called_once_with(team, a, "abc")
        sleep.assert_not_called()


def check_validation_error_notifies(result):
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        a = {"local": True, "host": "local", "path": "/clone", "suite": "suite"}
        res = {"hash": "abc", "result": result, "detail": "cannot run", "time": "now"}
        with patch.object(cl, "check_at", return_value=res, create=True), patch.object(cl, "tell_owner") as owner:
            cl.validate_one(team, a, "abc")
        assert list(cl.all_findings(team)) == []
        team.notify.assert_called_once()
        recipient, kind, text = team.notify.call_args.args
        assert (recipient, kind) == ("Skippy", "NOTE")
        assert "cannot run" in text
        owner.assert_called_once()


def test_validation_error_notifies_without_opening_findings():
    check_validation_error_notifies("error")


def test_validation_toolchain_notifies_without_opening_findings():
    check_validation_error_notifies("toolchain")


if __name__ == "__main__":
    failed = []
    for name, test in list(globals().items()):
        if name.startswith("test_") and callable(test):
            try:
                test()
            except Exception:
                failed.append(name)
                print(f"FAIL {name}")
                traceback.print_exc()
    print(f"{len(failed)} failed: {', '.join(failed)}")
    raise SystemExit(bool(failed))
