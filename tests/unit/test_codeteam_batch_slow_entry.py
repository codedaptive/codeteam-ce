import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_batch_slow_entry import batch_slow_entry


FLAG = {"total_s": 1200, "limit_s": 900, "steps": [
    {"step": "tests B (src/b)", "run_s": 800, "queued_s": 0},
    {"step": "tests A (src/a)", "run_s": 400, "queued_s": 0},
]}


def test_entry_reaching_slowest_zone_beats_earlier_nonmatching_entry():
    entries = [
        {"wo": "a", "zones": [f"A{i}" for i in range(5)]},
        {"wo": "b", "zones": ["B", *[f"Z{i}" for i in range(18)]]},
    ]
    owner = Mock(side_effect={"tests B (src/b)": "B", "tests A (src/a)": "A"}.get)
    assert batch_slow_entry(FLAG, entries, owner) is entries[1]
    owner.assert_called_once_with("tests B (src/b)")


def test_widest_entry_reaching_slowest_zone_wins():
    entries = [
        {"wo": "a", "zones": ["B", *[f"A{i}" for i in range(6)]]},
        {"wo": "b", "zones": ["B", *[f"Z{i}" for i in range(18)]]},
    ]
    owner = Mock(side_effect={"tests B (src/b)": "B", "tests A (src/a)": "A"}.get)
    assert batch_slow_entry(FLAG, entries, owner) is entries[1]


def test_equal_width_matching_entries_choose_earlier():
    entries = [{"wo": "a", "zones": ["A", "B"]}, {"wo": "b", "zones": ["B", "C"]}]
    owner = Mock(side_effect={"tests B (src/b)": "B", "tests A (src/a)": "A"}.get)
    assert batch_slow_entry(FLAG, entries, owner) is entries[0]


def test_no_entry_reaching_slowest_zone_chooses_first():
    entries = [{"wo": "a", "zones": ["A"]}, {"wo": "b", "zones": ["C", "D"]}]
    owner = Mock(side_effect={"tests B (src/b)": "B", "tests A (src/a)": "A"}.get)
    assert batch_slow_entry(FLAG, entries, owner) is entries[0]


def test_no_flag_chooses_first_without_resolving_owner():
    entries = [{"wo": "a", "zones": ["A"]}, {"wo": "b", "zones": ["B"]}]
    owner = Mock()
    assert batch_slow_entry(None, entries, owner) is entries[0]
    owner.assert_not_called()


def test_empty_steps_choose_first_without_resolving_owner():
    entries = [{"wo": "a", "zones": ["A"]}, {"wo": "b", "zones": ["B"]}]
    owner = Mock()
    assert batch_slow_entry({"total_s": 901, "limit_s": 900, "steps": []}, entries, owner) is entries[0]
    owner.assert_not_called()


def test_missing_steps_choose_first_without_resolving_owner():
    entries = [{"wo": "a", "zones": ["A"]}, {"wo": "b", "zones": ["B"]}]
    owner = Mock()
    assert batch_slow_entry({"total_s": 901, "limit_s": 900}, entries, owner) is entries[0]
    owner.assert_not_called()
