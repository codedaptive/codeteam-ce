#!/usr/bin/env -S python3 -u
"""Stage 2 and recheck rows identify their batch without changing other fields."""
import contextlib
import importlib.machinery
import importlib.util
import io
import subprocess
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, mock_open, patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_stage2_group", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)


def stamped(batches):
    """A step_results fake: the next batch, each row carrying the group keyword as the real one stamps it."""
    batches = iter(batches)
    return lambda *args, **kw: [row | ({"group": kw["group"]} if "group" in kw else {}) for row in next(batches)]


def test_stage2_record_assigns_group_to_every_row():
    results = [{"name": "one", "outcome": "PASS", "seconds": 1.24, "queued": 2},
               {"name": "two", "outcome": "FAIL", "seconds": 3.16, "stopped_by": "disk"}]
    for group in ("unit", "compile"):
        assert cl.stage2_record(results, group=group) == [
            {"step": "one", "result": "pass", "seconds": 1.2, "queued": 2, "group": group},
            {"step": "two", "result": "disk", "seconds": 3.2, "group": group}]


def test_stage2_record_without_group_omits_key():
    assert cl.stage2_record([{"name": "one", "outcome": "PASS", "seconds": 1}]) == [
        {"step": "one", "result": "pass", "seconds": 1}]


def test_check_integration_records_batch_groups_and_keeps_compile_environment():
    team = SimpleNamespace(c=lambda key, default: default, save_wo=Mock())
    rec = {"wo": "w", "zone": "A", "tree": "tree", "files": ["A/file"]}

    def run(tree, steps, env, **kwargs):
        for name, _ in reversed(steps):
            kwargs["on_result"]({"name": name, "outcome": "PASS", "seconds": 1})
        return True, []

    with patch.object(cl, "duplicate_rulings", return_value=[]), patch.object(cl, "reach", return_value=["A"]), \
            patch.object(cl, "compile_steps", return_value=[("compile", "c")]), \
            patch.object(cl, "repo_test_steps", return_value=[("units", "u")]), \
            patch.object(cl, "zone_tests", return_value=[("zone integration", "z")]), \
            patch.object(cl, "repo_integration_steps", return_value=[("repo integration", "r")]), \
            patch.object(cl, "team_env", return_value={}) as env, patch.object(cl, "run_steps", side_effect=run), \
            patch.object(cl, "changed_tracked", return_value=set()), \
            patch.object(cl, "restore_build_changes", return_value=[]), patch.object(cl, "made_stale", return_value=[]), \
            contextlib.redirect_stdout(io.StringIO()):
        assert cl.check_integration(team, rec, False) == ["A"]
    assert rec["stage2"] == [
        {"step": "compile", "result": "pass", "seconds": 1, "group": "compile"},
        {"step": "units", "result": "pass", "seconds": 1, "group": "unit"}]
    assert env.call_args_list == [call(team, "integration"), call(team, "unit")]


def test_stale_lock_row_uses_batch_kind():
    team = SimpleNamespace(save_wo=Mock())
    rec = {"wo": "w", "tree": "tree"}
    with patch.object(cl, "team_env", return_value={}), patch.object(cl, "run_steps", return_value=(True, [])), \
            patch.object(cl, "changed_tracked", return_value=set()), \
            patch.object(cl, "restore_build_changes", return_value=["Cargo.lock"]), \
            patch.object(cl, "made_stale", return_value=["Cargo.lock"]), contextlib.redirect_stdout(io.StringIO()):
        assert not cl.stage2_steps(team, rec, [], "integration", kind="compile")
    assert rec["stage2"] == [{"step": "committed lock files current", "result": "fail", "seconds": 0.0,
                               "group": "compile"}]


def test_integration_result_copies_group_only_when_present():
    row = {"M": "M", "wo": "w", "overlapping": [], "zones": ["A"]}
    results = [{"name": "compile", "outcome": "PASS", "seconds": 1.24, "group": "compile"},
               {"name": "legacy", "outcome": "FAIL", "seconds": 2, "tail": ["bad"]}]
    assert cl.integration_result(row, results, "now")["tests"] == [
        {"name": "compile", "result": "pass", "seconds": 1.2, "group": "compile"},
        {"name": "legacy", "result": "fail", "seconds": 2, "tail": ["bad"]}]


def test_stage2_rows_preserve_timing_and_record_paths():
    result = {"name": "tests A", "outcome": "PASS", "seconds": 2.4, "start": 100.1, "end": 102.5,
              "records": ["/p/.test-record.json"]}
    assert cl.stage2_record([result]) == [{"step": "tests A", "result": "pass", "seconds": 2.4,
                                         "start": 100.1, "end": 102.5, "records": ["/p/.test-record.json"]}]


def test_stage2_rows_keep_individually_present_zero_timestamps():
    results = [{"name": "start", "outcome": "PASS", "seconds": 1, "start": 0.0},
               {"name": "end", "outcome": "PASS", "seconds": 1, "end": 0.0}]
    assert cl.stage2_record(results) == [{"step": "start", "result": "pass", "seconds": 1, "start": 0.0},
                                          {"step": "end", "result": "pass", "seconds": 1, "end": 0.0}]


def test_recheck_rows_preserve_timing():
    row = {"M": "M", "wo": "w", "overlapping": [], "zones": ["A"]}
    result = {"name": "tests A", "outcome": "PASS", "seconds": 2.4, "start": 100.1, "end": 102.5}
    assert cl.integration_result(row, [result], "now")["tests"] == [
        {"name": "tests A", "result": "pass", "seconds": 2.4, "start": 100.1, "end": 102.5}]


def test_recheck_one_records_compile_then_integration_groups():
    team = SimpleNamespace(dir=Path("fake"))
    row = {"time": "then", "M": "M", "wo": "w", "overlapping": [], "zones": ["A"]}
    batches = [[{"name": "compile", "outcome": "PASS", "seconds": 1}],
               [{"name": "tests A", "outcome": "PASS", "seconds": 2}]]
    with patch.object(cl, "itest_lock", return_value=contextlib.nullcontext(), create=True), \
            patch.object(cl, "itest_checkout", return_value="tree"), \
            patch.object(cl, "recheck_steps", return_value=([("compile", "c")], [("tests A", "t")])), \
            patch.object(cl, "team_env", return_value={}), patch.object(cl, "step_results", side_effect=stamped(batches)), \
            patch.object(cl, "keep_recheck_logs"), patch.object(cl, "now", return_value="now"), \
            patch.object(cl, "report_slow_tests"), patch.object(cl, "landed_rec", return_value={}), \
            patch.object(cl, "apply_recheck_findings"), patch.object(cl, "complete_recheck"), \
            patch.object(Path, "open", mock_open()):
        result = cl.recheck_one(team, [row])
    assert result["tests"] == [{"name": "compile", "result": "pass", "seconds": 1, "group": "compile"},
                               {"name": "tests A", "result": "pass", "seconds": 2, "group": "integration"}]


def test_slow_tests_flag_ignores_group():
    rows = [{"step": "tests A (src)", "seconds": 1000, "queued": 50},
            {"name": "compile A", "seconds": 500}]
    expected = {"total_s": 950.0, "limit_s": 900,
                "steps": [{"step": "tests A (src)", "run_s": 950.0, "queued_s": 50}]}
    assert cl.slow_tests_flag(rows) == expected
    assert cl.slow_tests_flag([rows[0] | {"group": "integration"}, rows[1] | {"group": "compile"}]) == expected


if __name__ == "__main__":
    failed = 0
    for name, test in list(globals().items()):
        if name.startswith("test_") and callable(test):
            try:
                test()
                print(f"PASS {name}")
            except (Exception, SystemExit):
                failed += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    print(f"{failed} failed" if failed else "all passed")
    sys.exit(1 if failed else 0)
