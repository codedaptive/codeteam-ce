"""starving_lane: a lane that waits long for a slot behind lanes whose /exit was
cancelled for background work is named once per wait. Unit tests: the pure function only."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2.starving_lane import starving_lane  # noqa: E402

NOW = 1_000_000.0
HELD = {"a": {"bg_until": NOW + 300}, "b": {"bg_until": NOW - 1}}


class StarvingLaneTests(unittest.TestCase):
    def test_a_long_wait_behind_a_cancelled_exit_is_named(self):
        self.assertEqual(starving_lane([(NOW - 61 * 60, "c")], [], ["a", "b"], HELD, NOW),
                         [("starve", "c", 61, ("a",))])

    def test_every_lane_in_its_hold_is_named_in_order(self):
        st = {"b": {"bg_until": NOW + 60}, "a": {"bg_until": NOW + 300}}
        self.assertEqual(starving_lane([(NOW - 90 * 60, "c")], [], ["b", "a"], st, NOW),
                         [("starve", "c", 90, ("a", "b"))])

    def test_the_oldest_waiting_lane_is_the_one_named(self):
        waiting = [(NOW - 120 * 60, "c"), (NOW - 70 * 60, "d")]
        self.assertEqual(starving_lane(waiting, [], ["a"], HELD, NOW)[0][1], "c")

    def test_a_short_wait_is_not_named(self):
        self.assertEqual([], starving_lane([(NOW - 59 * 60, "c")], [], ["a"], HELD, NOW))

    def test_a_wait_behind_lanes_with_no_cancelled_exit_is_not_named(self):
        # b's hold has ended and d has none: they free their slots by the normal swap.
        self.assertEqual([], starving_lane([(NOW - 5 * 3600, "c")], [], ["b", "d"], HELD, NOW))

    def test_named_once_per_wait(self):
        st = {**HELD, "c": {"starve_alerted": True}}
        self.assertEqual([], starving_lane([(NOW - 5 * 3600, "c")], [], ["a"], st, NOW))

    def test_a_lane_started_this_tick_is_not_named(self):
        self.assertEqual([], starving_lane([(NOW - 5 * 3600, "c")], [("start", "c")], ["a"], HELD, NOW))

    def test_a_swap_under_way_is_not_named(self):
        self.assertEqual([], starving_lane([(NOW - 5 * 3600, "c")], [], ["a"], HELD, NOW, swapping=True))

    def test_nothing_waiting(self):
        self.assertEqual([], starving_lane([], [], ["a"], HELD, NOW))

    def test_the_threshold_can_be_given(self):
        self.assertEqual(starving_lane([(NOW - 10 * 60, "c")], [], ["a"], HELD, NOW, alert_min=10),
                         [("starve", "c", 10, ("a",))])


if __name__ == "__main__":
    unittest.main()
