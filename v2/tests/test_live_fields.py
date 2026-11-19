"""live_fields (work order teamslot, decision 7): what the deck takes from a live runner's queue-runner.json. Unit
tests: the pure function, with a stand-in for collect's finite."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2.deck.live_fields import live_fields  # noqa: E402


def finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


class LiveFieldsTests(unittest.TestCase):
    def test_finite_numbers_and_bool_holds_are_kept(self):
        self.assertEqual(live_fields({"used": 3, "budget": 8, "hold": True}, ("used", "budget"), ("hold",), finite),
                         {"used": 3, "budget": 8, "hold": True})

    def test_any_other_value_is_none(self):
        self.assertEqual(live_fields({"used": float("nan"), "hold": 1}, ("used", "budget"), ("hold",), finite),
                         {"used": None, "budget": None, "hold": None})

    def test_a_teams_object_gives_its_valid_entries(self):
        data = {"teams": {"acme": {"running": 2, "waiting": 1}, "bad": {"running": -1, "waiting": 0}}}
        self.assertEqual(live_fields(data, (), (), finite), {"teams": {"acme": {"running": 2, "waiting": 1}}})

    def test_no_teams_key_when_teams_is_not_an_object(self):
        for data in ({}, {"teams": None}, {"teams": [1]}):
            with self.subTest(data=data):
                self.assertEqual(live_fields(data, ("used",), (), finite), {"used": None})


if __name__ == "__main__":
    unittest.main()
