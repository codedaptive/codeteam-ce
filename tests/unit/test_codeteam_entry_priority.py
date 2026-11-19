import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_entry_priority import entry_priority


def test_severity_one_fix_is_priority_zero():
    assert entry_priority([{"fixes": ["one"]}], {"one": 1}) == 0


def test_severity_two_fix_is_priority_zero():
    assert entry_priority([{"fixes": ["two"]}], {"two": 2}) == 0


def test_severity_three_fix_is_priority_two():
    assert entry_priority([{"fixes": ["three"]}], {"three": 3}) == 2


def test_no_fixes_is_priority_one():
    assert entry_priority([], {}) == 1
    assert entry_priority([{}, {"fixes": None}], {"one": 1}) == 1


def test_mixed_severities_in_one_record_are_priority_zero():
    assert entry_priority([{"fixes": ["three", "two"]}], {"two": 2, "three": 3}) == 0


def test_mixed_severities_across_records_are_priority_zero():
    assert entry_priority([{"fixes": ["three"]}, {"fixes": ["two"]}], {"two": 2, "three": 3}) == 0


def test_unknown_fixes_are_priority_one():
    assert entry_priority([{"fixes": ["missing"]}], {}) == 1


def test_unknown_and_severity_three_are_priority_two():
    assert entry_priority([{"fixes": ["missing", "three"]}], {"three": 3}) == 2


def test_slow_fixes_do_not_affect_priority():
    assert entry_priority([{"slow_fixes": ["one"]}], {"one": 1}) == 1


def test_non_integer_severity_is_skipped():
    assert entry_priority([{"fixes": ["bad"]}], {"bad": "1"}) == 1
    assert entry_priority([{"fixes": ["bad", "three"]}], {"bad": "1", "three": 3}) == 2


def test_sort_preserves_queue_order_within_priority():
    items = [("new-first", [{}]), ("urgent", [{"fixes": ["one"]}]), ("new-second", [{}])]
    ordered = sorted(items, key=lambda item: entry_priority(item[1], {"one": 1}))
    assert [name for name, _ in ordered] == ["urgent", "new-first", "new-second"]
