import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_recheck_slow_source import recheck_slow_source


def test_batch_head_names_every_work_order_and_the_newest_zone():
    row = {"wo": "three", "M": "cccccccccccc", "batch": ["one", "two", "three"]}
    assert recheck_slow_source(row, {"three": {"zone": "C"}}.get) == (
        "one, two, three recheck at M cccccccccc", {"wo": "three", "zone": "C", "stage": 5, "commit": "cccccccccccc"})


def test_single_row_without_a_landed_record():
    row = {"wo": "w1", "M": "abcdefghijk"}
    assert recheck_slow_source(row, lambda wo: None) == (
        "w1 recheck at M abcdefghij", {"wo": "w1", "zone": None, "stage": 5, "commit": "abcdefghijk"})
