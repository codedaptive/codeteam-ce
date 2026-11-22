#!/usr/bin/env -S python3 -u
"""the slow-test rule (2026-11-14): the 15 minutes a landing's tests may take are their run time, not their waits.
Over it is a flag on the record, a NOTE and one follow-up per zone (at a recheck, only when a covered work order's
Stage 2 was over too), closed by --fixes slow#N; never a hold.
The unit tests, including a step's "ran" and the server slow#2 timing tables (the parser of
zone-tool's run lines is tests/unit/land-ran-seconds.py); git, notify,
the clock, the queue and the findings lock are faked. Some read or write a fixture file in a temp folder; that alone
does not make a test an integration test. The tests that take the real findings lock are in
tests/integration/land-slow-tests.py."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
loader = importlib.machinery.SourceFileLoader("cl_slow", os.environ.get("CODETEAM_LAND", str(ROOT / "bin" / "codeteam-land")))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)


def team_at(path):
    return SimpleNamespace(dir=path, manifest="team.toml", zones={"cli": ["bin"], "gadget": ["gadget"]},
                           m={"assistants": [{"name": "Designer", "role": "designer"}]},
                           c=lambda key, default: "Orchestrator", notify=Mock(), log=Mock(),
                           save_wo=Mock(), repo=path, integration="integration")


def flag():
    return {"total_s": 960.0, "limit_s": 900, "steps": [
        {"step": "tests cli (bin)", "run_s": 600.0, "queued_s": 200.0},
        {"step": "unit tests (tests/unit)", "run_s": 360.0, "queued_s": 0.0}]}


def rows():
    return [{"step": "tests cli (bin)", "result": "pass", "seconds": 800.0, "queued": 200},
            {"step": "unit tests (tests/unit)", "result": "pass", "seconds": 360.0}]


def test_step_run_seconds():
    assert cl.step_run_seconds({"seconds": 10.0}) == 10.0
    assert cl.step_run_seconds({"seconds": 10.0, "queued": None}) == 10.0
    assert cl.step_run_seconds({"seconds": 10.0, "queued": 3.0}) == 7.0
    assert cl.step_run_seconds({"seconds": 10.0, "queued": 11.0}) == 0.0


def test_step_run_seconds_prefers_ran():
    assert cl.step_run_seconds({"seconds": 202.0, "queued": 22, "ran": 7}) == 7


def test_step_run_seconds_preserves_zero_ran():
    assert cl.step_run_seconds({"seconds": 202.0, "queued": 22, "ran": 0}) == 0


def test_server_slow2_uses_job_run_times_not_lock_waits():
    # The unit and integration timing tables of the server follow-up slow#2.
    data = [
        ("crates/host-lock", 8.8, 3, 4), ("crates/server-core", 28.5, 1, 15),
        ("crates/server-host", 49.8, 4, 15), ("crates/cli-support", 65.4, 8, 5),
        ("crates/cli-index", 112.0, 23, 22), ("crates/cli-nav", 138.4, 9, 16),
        ("crates/cli-host", 170.8, 19, 11), ("crates/cli-botlink", 202.0, 22, 7),
        ("crates/host-lock", 82.2, 76, 4), ("crates/server-core", 93.0, 2, 7),
        ("crates/server-host", 109.3, 8, 6), ("crates/cli-support", 121.3, 2, 8),
        ("crates/cli-index", 135.2, 2, 10), ("crates/cli-nav", 145.0, 2, 6),
        ("crates/cli-host", 160.7, 5, 9), ("crates/cli-botlink", 174.6, 5, 8),
        ("crates/widgets/tests/server", 218.0, 3, 36), ("crates/widgets/tests/cli", 299.6, 2, 77),
    ]
    rows = [{"step": f"tests server ({path})", "seconds": seconds, "queued": queued, "ran": ran}
            for path, seconds, queued, ran in data]
    without_ran = [{key: value for key, value in row.items() if key != "ran"} for row in rows]
    assert cl.slow_tests_flag(without_ran)["total_s"] == 2118.6
    assert cl.slow_tests_flag(rows) is None  # 266 s, below the 900 s limit.


def test_slow_flag_reports_ran_for_over_limit_steps():
    assert cl.slow_tests_flag([
        {"step": "tests server (crates/server)", "seconds": 1300.0, "queued": 100, "ran": 901},
    ]) == {"total_s": 901, "limit_s": 900, "steps": [
        {"step": "tests server (crates/server)", "run_s": 901, "queued_s": 100}]}


def test_is_test_step():
    for name in ("tests cli (bin)", "tests gadget (its lane's test)", "unit tests (tests/unit)",
                 "integration tests (tests/integration)", "rits acme (packages/kits/VaultKit)",
                 "rits gadget (its lane's test)"):
        assert cl.is_test_step(name), name
    for name in ("type check", "repo gates", "compile cli (bin)", "committed lock files current"):
        assert not cl.is_test_step(name), name


def test_step_owner():
    team = team_at(Path("/unused"))
    with patch.object(cl, "zone_of_file", side_effect=lambda team, folder: {"bin": "cli"}.get(folder)):
        assert cl.step_owner(team, "tests cli (bin)") == "cli"
        assert cl.step_owner(team, "unit tests (bin)") == "cli"
        assert cl.step_owner(team, "unit tests (tests/unit)") == "orc"
        assert cl.step_owner(team, "rits VaultKit (packages/kits/VaultKit)") == "VaultKit"
        assert cl.step_owner(team, "rits gadget (its lane's test)") == "gadget"


def test_followup_zone_is_the_slowest_steps_zone_when_it_holds_a_changed_file():
    team = team_at(Path("/unused"))
    assert cl.followup_zone(team, "tests gadget", "cli", ["bin/x", "gadget/y"]) == "gadget"
    assert cl.followup_zone(team, "tests cli (bin)", "cli", []) == "cli"


def test_followup_zone_is_the_work_orders_own_when_the_slowest_zone_holds_no_changed_file():
    # A tooling work order reached 39 zones, and WidgetStoreKit got
    # slow#17 for its own 242 s step, which the change never touched. The zone whose change made the landing wide
    # gets the follow-up.
    team = team_at(Path("/unused"))
    assert cl.followup_zone(team, "tests gadget", "cli", ["bin/x"]) == "cli"
    assert cl.followup_zone(team, "rits gadget", "cli", []) == "cli"


def test_followup_zone_orc_holds_a_file_no_zone_owns():
    team = team_at(Path("/unused"))
    assert cl.followup_zone(team, "unit tests (tests/unit)", "cli", ["tests/unit/t.py"]) == "orc"
    assert cl.followup_zone(team, "unit tests (tests/unit)", "cli", ["bin/x"]) == "cli"


def test_followup_zone_without_the_work_orders_zone_is_the_slowest_steps_zone():
    team = team_at(Path("/unused"))
    assert cl.followup_zone(team, "tests gadget", None, ["bin/x"]) == "gadget"


def test_a_followup_for_the_work_orders_own_zone_says_why_it_has_it():
    team = team_at(Path("/unused"))
    entry = {"id": "slow#3", "zone": "cli", "from": {"wo": "w1", "stage": 2, "commit": "abcdefghijk"},
             "total_s": 960.0, "steps": [{"step": "tests gadget", "run_s": 960.0, "queued_s": 0.0}]}
    why = ("Its slowest tests are zone gadget's, which holds no file this landing changed, so the follow-up is this "
           "work order's zone's: find what in its change made the landing reach that far.")
    assert why in cl.slow_followup_request(team, entry)
    assert "holds no file" not in cl.slow_followup_request(team, entry | {"zone": "gadget"})


def test_rit_steps_count_their_run_and_not_their_queue():
    # a calling zone's RIT step ("rits <zone> (...)") is a test step, so its run
    # counts toward the limit and its build-queue wait does not.
    assert cl.slow_tests_flag([{"step": "rits VaultKit (packages/kits/VaultKit)", "seconds": 1250.0, "queued": 300},
                               {"step": "type check", "seconds": 4000}]) == {
        "total_s": 950.0, "limit_s": 900,
        "steps": [{"step": "rits VaultKit (packages/kits/VaultKit)", "run_s": 950.0, "queued_s": 300}]}


def test_slow_tests_threshold_and_queue_exclusion():
    assert cl.slow_tests_flag([{"step": "tests cli (bin)", "seconds": 900.0}]) is None
    assert cl.slow_tests_flag([{"step": "tests cli (bin)", "seconds": 1000.0, "queued": 200}]) is None
    assert cl.slow_tests_flag([{"step": "type check", "seconds": 2000}]) is None
    assert cl.slow_tests_flag([{"name": "tests cli (bin)", "seconds": 900.1}]) == {
        "total_s": 900.1, "limit_s": 900,
        "steps": [{"step": "tests cli (bin)", "run_s": 900.1, "queued_s": 0.0}]}


def test_slow_tests_flag_orders_and_records_all_test_steps():
    assert cl.slow_tests_flag([rows()[1], {"step": "repo gates", "seconds": 5000}, rows()[0]]) == flag()


def test_slow_tests_flag_preserves_input_order_for_ties():
    assert cl.slow_tests_flag([
        {"step": "tests gadget", "seconds": 500.0},
        {"step": "tests cli (bin)", "seconds": 500.0},
    ]) == {"total_s": 1000.0, "limit_s": 900, "steps": [
        {"step": "tests gadget", "run_s": 500.0, "queued_s": 0.0},
        {"step": "tests cli (bin)", "run_s": 500.0, "queued_s": 0.0},
    ]}


def test_parallel_test_steps_count_only_once():
    rows = [{"step": "tests cli (bin)", "seconds": 600, "queued": 0, "end": 700},
            {"name": "tests gadget", "seconds": 600, "queued": 0, "end": 700}]
    assert cl.slow_tests_flag(rows) is None


def test_serial_test_steps_add_and_preserve_step_details():
    rows = [{"step": "tests cli (bin)", "seconds": 600, "queued": 0, "end": 600},
            {"name": "tests gadget", "seconds": 600, "queued": 0, "end": 1200}]
    assert cl.slow_tests_flag(rows) == {"total_s": 1200, "limit_s": 900, "steps": [
        {"step": "tests cli (bin)", "run_s": 600, "queued_s": 0},
        {"step": "tests gadget", "run_s": 600, "queued_s": 0}]}


def test_slow_note_explains_parallel_steps_count_once():
    note = cl.slow_tests_note("w", "Stage 2", flag(), "follow-up opened")
    assert "side by side" in note.lower()


def test_a_new_land_attempt_drops_the_last_attempts_flag():
    # A flag describes one attempt's Stage 2; a later attempt that fails must not keep an earlier one's flag.
    saved = {}
    team = SimpleNamespace(wo=lambda wo: {"wo": wo, "tree": "t", "slow_tests": {"old": True}},
                           save_wo=lambda rec: saved.update({rec["wo"]: dict(rec)}))
    with patch.object(cl, "entry_path", return_value=None), patch.object(cl, "put_back_set_merge"), \
            patch.object(cl, "carried_check", return_value=None), \
            patch.object(cl, "check_work_order", side_effect=SystemExit(3)):
        try:
            cl.checked_members(team, ["w1"])
        except SystemExit:
            pass
    assert saved == {"w1": {"wo": "w1", "tree": "t", "stage2": []}}


def test_cmd_wo_tag_prints_slow_fixes():
    team = team_at(Path("/unused")); rec = {"wo": "w1", "fixes": ["w1#1"], "slow_fixes": ["slow#1"]}; team.wo = Mock(return_value=rec)
    output = io.StringIO()
    with patch.object(cl, "tag_wo"), contextlib.redirect_stdout(output):
        cl.cmd_wo_tag(team, SimpleNamespace(wo="w1", feature=None, fixes=[]))
    assert output.getvalue() == "w1: feature w1; fixes w1#1, slow#1\n"


def test_bookkeeping_survives_a_close_error():
    team = team_at(Path("/unused"))
    with patch.object(cl, "docs_pass"), patch.object(cl, "now", return_value="NOW"), \
            patch.object(cl, "close_slow_followups", side_effect=OSError("disk")):
        cl.member_bookkeeping(team, {"wo": "w1", "slow_fixes": ["slow#1"]}, {"recheck": False})
    assert team.log.call_args_list == [call({"time": "NOW", "wos": ["w1"], "slow_tests_error": "OSError: disk"})]


def stage2_records(stage_rows, old=True):
    return [{"wo": wo, "zone": "cli", "tree": f"tree{n}", "stage2": stage_rows} | ({"slow_tests": {"old": True}} if old else {})
            for n, wo in ((1, "w1"), (2, "w2"))]


def run_stage2(team, records, check=(["cli"], ["cli"])):
    """check_and_queue over the two records; check is check_combined_members' answer, or the exception it raises."""
    with contextlib.ExitStack() as stack:
        for name, value in {"checked_members": [(r, None) for r in records], "out": "abcdefghijk",
                            "merge_checked_base": None, "changed_files": [], "own_base": "base", "now": "NOW",
                            "queue_notices": None, "queue_entry": {"review": "pending"},
                            "stage3_request": "review"}.items():
            stack.enter_context(patch.object(cl, name, return_value=value))
        stack.enter_context(patch.object(cl, "other_member_heads", return_value=[], create=True))
        stack.enter_context(patch.object(cl, "check_combined_members",
                                         **({"side_effect": check} if isinstance(check, BaseException) else {"return_value": check})))
        stack.enter_context(patch.object(cl, "Lock", return_value=contextlib.nullcontext()))
        queue = stack.enter_context(patch.object(cl, "queue_stage3", return_value={"Reviewer": ["w1"]}))
        with contextlib.redirect_stdout(io.StringIO()):
            cl.check_and_queue(team, SimpleNamespace(wo="w1"), ["w1", "w2"])
        queue.assert_called_once_with(team, records, {"review": "pending"}, "NOW")
    return records


def run_recheck(team, outcome, landed=None):
    row = {"time": "then", "wo": "w1", "M": "abcdefghijk", "overlapping": [], "zones": ["cli"]}
    results = [{"name": "tests cli (bin)", "outcome": outcome, "seconds": 800.0, "queued": 200},
               {"name": "unit tests (tests/unit)", "outcome": "PASS", "seconds": 360.0}]
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(cl, "itest_lock", return_value=contextlib.nullcontext(), create=True))
        for name, value in {"itest_checkout": "tree", "recheck_steps": ([], ["test"]), "team_env": {},
                            "keep_recheck_logs": None, "landed_rec": landed or {}, "now": "NOW"}.items():
            stack.enter_context(patch.object(cl, name, return_value=value))
        stack.enter_context(patch.object(cl, "step_results", side_effect=[[], results]))
        apply = stack.enter_context(patch.object(cl, "apply_recheck_findings"))
        complete = stack.enter_context(patch.object(cl, "complete_recheck"))
        result = cl.recheck_one(team, [row])
    return row, result, apply, complete


def test_stage2_under_limit_removes_old_flag_and_queues_without_slow_notices():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); records = run_stage2(team, stage2_records([{"step": "tests cli (bin)", "seconds": 900}]))
        assert all("slow_tests" not in r for r in records)
        assert [r.get("stage2_tests_s") for r in records] == [900.0, 900.0]
        assert team.notify.call_args_list == [call("Reviewer", "REQUEST", "review")]


def test_stage2_over_limit_records_measure_on_all_members():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        records = stage2_records(rows())
        for record in records:
            record["stage2_tests_s"] = 1200.0
        with patch.object(cl, "report_slow_tests"):
            run_stage2(team, records)
        assert [r.get("stage2_tests_s") for r in records] == [960.0, 960.0]


def test_stage2_not_passed_flags_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); records = stage2_records(rows(), old=False)
        try:
            run_stage2(team, records, SystemExit(3))
        except SystemExit as ex:
            assert ex.code == 3
        else:
            raise AssertionError("a failed Stage 2 was queued")
        assert team.notify.call_args_list == []
        assert not (team.dir / "slow-tests.json").exists()
        assert all("slow_tests" not in r for r in records)


def test_recheck_survives_a_followup_error():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        with patch.object(cl, "open_slow_followup", side_effect=OSError("disk")):
            row, result, apply, complete = run_recheck(team, "PASS", {"zone": "cli", "stage2_tests_s": 960.0})
        assert result["slow_tests"] == flag()
        apply.assert_called_once()
        complete.assert_called_once_with(team, row, "NOW")
        assert team.log.call_args_list == [call({"time": "NOW", "slow_tests_error": "OSError: disk"})]
        assert team.notify.call_args_list == []


def test_recheck_unrecorded_stage2_sends_only_load_note():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        with patch.object(cl, "open_slow_followup") as opened:
            row, result, apply, complete = run_recheck(team, "PASS")
        assert result["slow_tests"] == flag()
        opened.assert_not_called()
        team.notify.assert_called_once_with("Orchestrator", "NOTE", "SLOW TESTS w1 recheck at M abcdefghij: Stage 5 tests ran 16.0 min of run time (waits excluded, steps side by side counted once; limit 15); slowest: tests cli (bin) 10.0 min, unit tests (tests/unit) 6.0 min; load, not a follow-up: no work order it covers had Stage 2 tests over 15 min (w1 Stage 2 not recorded); a flag, not a hold.")
        complete.assert_called_once_with(team, row, "NOW")


def test_tag_open_slow_id_without_finding():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); (team.dir / "slow-tests.json").write_text(json.dumps([{"id": "slow#1", "state": "open"}]))
        rec = {}; cl.tag_wo(team, rec, None, ["slow#1"])
        assert rec == {"slow_fixes": ["slow#1"]}
        assert not (team.dir / "findings" / "slow.json").exists()


def test_tag_unknown_slow_id_refused():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); rec = {}; err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                cl.tag_wo(team, rec, None, ["slow#9"])
        except SystemExit:
            pass
        else:
            raise AssertionError("unknown follow-up accepted")
        assert err.getvalue() == f"--fixes slow#9: no open slow-tests follow-up slow#9 ({tmp}/slow-tests.json)\n"
        assert rec == {} and not (team.dir / "findings" / "slow.json").exists()


def test_tag_closed_slow_id_refused():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); (team.dir / "slow-tests.json").write_text(json.dumps([{"id": "slow#1", "state": "closed"}]))
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                cl.tag_wo(team, {}, None, ["slow#1"])
        except SystemExit:
            pass
        else:
            raise AssertionError("closed follow-up accepted")
        assert err.getvalue() == f"--fixes slow#1: no open slow-tests follow-up slow#1 ({tmp}/slow-tests.json)\n"
        assert not (team.dir / "findings" / "slow.json").exists()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("all passed")
