"""Selection of idle lanes whose exits have been observed."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2.exited_idle_lanes import exited_idle_lanes  # noqa: E402


def test_flagged_absent_lane_is_selected():
    assert exited_idle_lanes({"a": "absent"}, {"a": {"clean_on_exit": True}}, set()) == [("a", True)]


def test_flagged_lane_missing_status_is_selected():
    assert exited_idle_lanes({}, {"a": {"clean_on_exit": True}}, set()) == [("a", True)]


@pytest.mark.parametrize("status", ["idle", "working", "done"])
def test_flagged_present_lane_is_not_selected(status):
    assert exited_idle_lanes({"a": status}, {"a": {"clean_on_exit": True}}, set()) == []


def test_unflagged_absent_lane_is_not_selected():
    assert exited_idle_lanes({"a": "absent"}, {"a": {}}, set()) == []


@pytest.mark.parametrize("flag", [None, False])
def test_false_flagged_absent_lane_is_not_selected(flag):
    assert exited_idle_lanes({"a": "absent"}, {"a": {"clean_on_exit": flag}}, set()) == []


def test_selected_keys_are_sorted():
    st = {"z": {"clean_on_exit": True}, "b": {"clean_on_exit": True},
          "a": {"clean_on_exit": True}, "c": {"clean_on_exit": False}}
    assert exited_idle_lanes({"z": "absent", "b": "working", "c": "absent"}, st, set()) == [
        ("a", True), ("z", True)]


def test_flagged_absent_lane_with_mail_is_not_cleaned():
    assert exited_idle_lanes({"a": "absent"}, {"a": {"clean_on_exit": True}}, {"a"}) == [("a", False)]


def test_sorted_absent_lanes_preserve_individual_mail_decisions():
    st = {"z": {"clean_on_exit": True}, "a": {"clean_on_exit": True}}
    assert exited_idle_lanes({"z": "absent", "a": "absent"}, st, {"a"}) == [("a", False), ("z", True)]


def test_unflagged_absent_lane_with_mail_is_not_selected():
    assert exited_idle_lanes({"a": "absent"}, {"a": {}}, {"a"}) == []


def test_flagged_working_lane_with_mail_is_not_selected():
    assert exited_idle_lanes({"a": "working"}, {"a": {"clean_on_exit": True}}, {"a"}) == []
