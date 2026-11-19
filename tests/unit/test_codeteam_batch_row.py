import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_batch_row import batch_row


def test_union_row_preserves_order_and_only_contract_fields():
    rows = [
        {"time": "t1", "M": "a", "wo": "one", "overlapping": ["x", "y"], "zones": ["Z", "A"],
         "files": ["a", "b"], "set": ["one", "extra"], "done": "done"},
        {"time": "t2", "M": "b", "wo": "two", "overlapping": ["y", "z"], "zones": ["B", "A"],
         "checkout_failed": "t"},
        {"time": "t3", "M": "c", "wo": "three", "overlapping": ["x"], "zones": ["C"],
         "files": ["b", "c"], "set": ["extra", "three"]},
    ]
    assert batch_row(rows) == {"time": "t3", "M": "c", "wo": "three", "overlapping": ["x", "y", "z"],
                               "zones": ["A", "B", "C", "Z"], "files": ["a", "b", "c"],
                               "set": ["one", "extra", "two", "three"], "batch": ["one", "two", "three"]}
