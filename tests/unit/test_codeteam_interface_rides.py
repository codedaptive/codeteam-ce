import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_interface_rides import interface_rides


def test_touching_open_order_wakes():
    diff = Mock(return_value=["B/caller.rs"])
    assert interface_rides("B", ["B/caller.rs"], [{"zone": "B"}], diff) is False


def test_non_touching_open_order_rides():
    assert interface_rides("B", ["B/caller.rs"], [{"zone": "B"}],
                           lambda rec: ["B/other.rs"]) is True


def test_no_open_orders_rides():
    assert interface_rides("B", ["B/caller.rs"], [], Mock()) is True


def test_queued_order_is_ignored():
    diff = Mock(return_value=["B/caller.rs"])
    assert interface_rides("B", ["B/caller.rs"], [{"zone": "B", "queued": True}], diff) is True
    diff.assert_not_called()


def test_other_zone_order_is_ignored():
    diff = Mock(return_value=["B/caller.rs"])
    assert interface_rides("B", ["B/caller.rs"], [{"zone": "C"}], diff) is True
    diff.assert_not_called()


def test_unknown_diff_wakes():
    assert interface_rides("B", ["B/caller.rs"], [{"zone": "B"}],
                           Mock(side_effect=RuntimeError("unknown"))) is False


def test_missing_callers_with_open_order_wakes_without_diff():
    diff = Mock()
    assert interface_rides("B", None, [{"zone": "B"}], diff) is False
    diff.assert_not_called()


def test_missing_callers_without_open_order_rides_without_diff():
    diff = Mock()
    assert interface_rides("B", None, [], diff) is True
    diff.assert_not_called()


def test_any_touching_order_wakes():
    records = [{"zone": "B", "tree": "first"}, {"zone": "B", "tree": "second"}]
    diff = Mock(side_effect=[["B/other.rs"], ["B/caller.rs"]])
    assert interface_rides("B", ["B/caller.rs"], records, diff) is False
