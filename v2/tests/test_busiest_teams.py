"""busiest_teams (work order teamslot, decision 7): the deck's order of teams by build queue counts. Unit tests:
the pure function only."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2.deck.busiest_teams import busiest_teams  # noqa: E402


class BusiestTeamsTests(unittest.TestCase):
    def test_more_running_comes_first(self):
        self.assertEqual(busiest_teams({"widgets": {"running": 1, "waiting": 0}, "acme": {"running": 8, "waiting": 3},
                                        "lab": {"running": 0, "waiting": 9}}),
                         [("acme", 8, 3), ("widgets", 1, 0), ("lab", 0, 9)])

    def test_a_running_tie_puts_more_waiting_first(self):
        self.assertEqual(busiest_teams({"a": {"running": 2, "waiting": 1}, "b": {"running": 2, "waiting": 4}}),
                         [("b", 2, 4), ("a", 2, 1)])

    def test_a_full_tie_is_in_name_order(self):
        self.assertEqual(busiest_teams({"zeta": {"running": 1, "waiting": 2}, "widgets": {"running": 1, "waiting": 0},
                                        "acme": {"running": 8, "waiting": 3}, "alpha": {"running": 1, "waiting": 2},
                                        "-": {"running": 1, "waiting": 2}}),
                         [("acme", 8, 3), ("-", 1, 2), ("alpha", 1, 2), ("zeta", 1, 2), ("widgets", 1, 0)])

    def test_an_empty_dict_gives_an_empty_list(self):
        self.assertEqual(busiest_teams({}), [])

    def test_a_count_that_is_not_a_number_counts_as_zero(self):
        self.assertEqual(busiest_teams({"a": {"running": True, "waiting": "3"}, "b": {"waiting": 1}, "c": 5,
                                        "d": {"running": float("nan"), "waiting": None}}),
                         [("b", 0, 1), ("a", 0, 0), ("c", 0, 0), ("d", 0, 0)])


if __name__ == "__main__":
    unittest.main()
