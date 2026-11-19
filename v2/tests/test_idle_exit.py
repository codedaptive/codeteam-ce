import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from codeteam2.idle_exit import IDLE_EXIT_H  # noqa: E402
from codeteam2.scheduler import plan  # noqa: E402

NOW = 1_000_000.0


def _plan_idle(minutes, keep_awake=frozenset()):
    return plan(
        sessions=[("a", "lane")],
        status={"a": "idle"},
        pending={},
        st={"a": {"state_since": NOW - minutes * 60}},
        now=NOW,
        cap=16,
        swap_idle_min=20,
        blocked_alert_min=2,
        gather_s=0,
        idle_exit_min=IDLE_EXIT_H * 60,
        keep_awake=keep_awake,
    )


def test_idle_lane_stops_after_61_minutes():
    assert ("stop", "a", "idle") in _plan_idle(61)


def test_idle_lane_does_not_stop_after_59_minutes():
    assert not [action for action in _plan_idle(59) if action[:2] == ("stop", "a")]


def test_keep_awake_lane_does_not_stop_after_61_minutes():
    assert not [action for action in _plan_idle(61, keep_awake={"a"}) if action[:2] == ("stop", "a")]
