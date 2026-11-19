import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_recheck_slow_report import recheck_slow_report


FLAG = {"total_s": 960.0}
ROW = {"wo": "three", "batch": ["one", "two", "three"], "M": "cccccccccccc"}


def setup(records):
    team = SimpleNamespace(notify=Mock(), log=Mock(), c=Mock(return_value="Orchestrator"))
    land = SimpleNamespace(landed_rec=Mock(side_effect=lambda team, wo: records.get(wo)),
                           SLOW_TESTS_LIMIT_S=900, report_slow_tests=Mock(),
                           slow_tests_note=Mock(side_effect=lambda head, stage, flag, suffix: suffix),
                           now=Mock(return_value="NOW"))
    return team, land


def test_no_flag_does_nothing():
    team, land = setup({})
    recheck_slow_report(team, land, None, ROW)
    land.landed_rec.assert_not_called()
    land.report_slow_tests.assert_not_called()
    team.notify.assert_not_called()
    team.log.assert_not_called()


def test_only_slow_work_order_supplies_source_and_files():
    team, land = setup({"one": {"zone": "A", "stage2_tests_s": 1000, "files": ["a", "shared"]},
                        "two": {"zone": "B", "stage2_tests_s": 100, "files": ["b"]},
                        "three": {"zone": "C"}})
    recheck_slow_report(team, land, FLAG, ROW)
    land.report_slow_tests.assert_called_once_with(team, FLAG, "one, two, three recheck at M cccccccccc", "Stage 5",
        {"wo": "one", "zone": "A", "stage": 5, "commit": "cccccccccccc"}, ["a", "shared"])
    team.notify.assert_not_called()


def test_newest_slow_work_order_is_source_and_files_are_ordered_union():
    team, land = setup({"one": {"zone": "A", "stage2_tests_s": 1000, "files": ["a", "shared"]},
                        "two": {"zone": "B", "stage2_tests_s": 901, "files": ["shared", "b"]},
                        "three": {"zone": "C", "stage2_tests_s": 100}})
    recheck_slow_report(team, land, FLAG, ROW)
    land.report_slow_tests.assert_called_once_with(team, FLAG, "one, two, three recheck at M cccccccccc", "Stage 5",
        {"wo": "two", "zone": "B", "stage": 5, "commit": "cccccccccccc"}, ["a", "shared", "b"])


def test_none_over_notifies_load_with_each_stage2_figure():
    team, land = setup({"w1": {"stage2_tests_s": 240.0}, "w2": {}})
    row = {"wo": "w2", "batch": ["w1", "w2"], "M": "abcdefghijk"}
    recheck_slow_report(team, land, FLAG, row)
    text = "load, not a follow-up: no work order it covers had Stage 2 tests over 15 min (w1 Stage 2 4.0 min, w2 Stage 2 not recorded)"
    land.slow_tests_note.assert_called_once_with("w1, w2 recheck at M abcdefghij", "Stage 5", FLAG, text)
    team.notify.assert_called_once_with("Orchestrator", "NOTE", text)
    land.report_slow_tests.assert_not_called()


def test_unrecorded_single_work_order_is_load():
    team, land = setup({})
    recheck_slow_report(team, land, FLAG, {"wo": "w1", "M": "abcdefghijk"})
    team.notify.assert_called_once_with("Orchestrator", "NOTE", "load, not a follow-up: no work order it covers had Stage 2 tests over 15 min (w1 Stage 2 not recorded)")
    land.report_slow_tests.assert_not_called()


def test_exactly_900_is_not_over():
    team, land = setup({"w1": {"stage2_tests_s": 900.0}})
    recheck_slow_report(team, land, FLAG, {"wo": "w1", "M": "abcdefghijk"})
    team.notify.assert_called_once_with("Orchestrator", "NOTE", "load, not a follow-up: no work order it covers had Stage 2 tests over 15 min (w1 Stage 2 15.0 min)")
    land.report_slow_tests.assert_not_called()


def test_load_notification_error_is_logged_and_not_raised():
    team, land = setup({})
    team.notify.side_effect = OSError("disk")
    recheck_slow_report(team, land, FLAG, {"wo": "w1", "M": "abcdefghijk"})
    team.log.assert_called_once_with({"time": "NOW", "slow_tests_error": "OSError: disk"})
