import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_batch_owner import batch_owner


ROWS = [{"wo": "one", "zones": ["A", "B"]}, {"wo": "two", "zones": ["B"]},
        {"wo": "three", "zones": ["C"]}]


def test_newest_row_reaching_zone_owns_it():
    assert batch_owner(ROWS, "B") == {"wo": "two", "zones": ["B"]}


def test_unknown_zone_falls_back_to_newest():
    assert batch_owner(ROWS, "D") == {"wo": "three", "zones": ["C"]}


def test_no_zone_falls_back_to_newest():
    assert batch_owner(ROWS, None) == {"wo": "three", "zones": ["C"]}
