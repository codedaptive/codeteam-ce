"""share/codeteam_carried_order.py (Orc-Codegraph #4653, D559): a work order record as the carried-commits check weighs
it. Unit tests (rule 11): git's commit list is a fake."""
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
import codeteam_carried_order
from codeteam_carried_order import Order


def order_of(rec):
    """Order.of over a fake commit list, with the (tree, landing) pairs it asked for."""
    asked = []
    def fake(tree, landing):
        asked.append((tree, landing))
        return ["c2", "c1"]
    with patch.object(codeteam_carried_order, "unlanded_commits", fake):
        return Order.of(rec, "landing"), asked


def test_a_record_gives_its_name_unlanded_commits_and_cut_time():
    order, asked = order_of({"wo": "host", "tree": "/t/host", "cut": "2026-11-17T09:00:00-06:00"})
    assert order == Order("host", ["c2", "c1"], datetime(2026, 11, 17, 15, 0, tzinfo=timezone.utc))
    assert asked == [("/t/host", "landing")]


def test_a_stand_in_record_without_a_cut_time_counts_as_cut_first():
    # wo-retire's record for a tree wo-cut never recorded; a refused retire leaves it open.
    order, asked = order_of({"wo": "lost", "tree": "/t/lost", "unregistered": True})
    assert order.cut == datetime(1, 1, 1, tzinfo=timezone.utc)
    assert asked == [("/t/lost", "landing")]


def test_a_record_with_no_tree_asks_for_none():
    _, asked = order_of({"wo": "bare", "cut": "2026-11-17T09:00:00-06:00"})
    assert asked == [(None, "landing")]
