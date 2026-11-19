import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_entry_priority import entry_priority
from codeteam_ready_batch import ready_batch


def test_first_ready_unowed_entry_goes_first_even_after_owed_entries():
    items = [("a", {"review": "land", "integration": "owed"}),
             ("held", {"review": "land", "hold": True}),
             ("pending", {"review": "pending"}),
             ("b", {"review": "land"}), ("c", {"review": "land"})]
    assert ready_batch(items) == ("b", [])


def test_all_ready_owed_entries_return_in_queue_order():
    items = [("b", {"review": "land", "integration": "owed"}),
             ("held", {"review": "land", "hold": True, "integration": "owed"}),
             ("pending", {"review": "pending", "integration": "owed"}),
             ("a", {"review": "land", "integration": "owed"})]
    assert ready_batch(items) == (None, ["b", "a"])


def test_no_ready_entries_returns_empty_batch():
    assert ready_batch([("x", {"review": "pending"}), ("y", {"review": "land", "hold": True})]) == (None, [])


def test_only_exact_owed_marker_is_owed():
    assert ready_batch([("a", {"review": "land", "integration": "passed"})]) == ("a", [])


def test_priority_sorted_unowed_entries_choose_urgent_fix():
    items = [("new", {"review": "land"}), ("urgent", {"review": "land"})]
    records = {"new": [{}], "urgent": [{"fixes": ["one"]}]}
    ordered = sorted(items, key=lambda item: entry_priority(records[item[0]], {"one": 1}))
    assert ready_batch(ordered) == ("urgent", [])


def test_priority_sorted_owed_batch_keeps_merge_order():
    items = [(name, {"review": "land", "integration": "owed"}) for name in ("minor", "new", "urgent")]
    records = {"minor": [{"fixes": ["three"]}], "new": [{}], "urgent": [{"fixes": ["two"]}]}
    ordered = sorted(items, key=lambda item: entry_priority(records[item[0]], {"two": 2, "three": 3}))
    assert ready_batch(ordered) == (None, ["urgent", "new", "minor"])
