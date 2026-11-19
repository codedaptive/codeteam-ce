"""teams_chips (work order teamslot, decision 7): the chips of the BUILDS teams row. Unit tests: the pure function
only."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2.deck.teams_chips import teams_chips  # noqa: E402


class TeamsChipsTests(unittest.TestCase):
    def test_a_live_runner_lists_teams_busiest_first(self):
        runner = {"state": "live", "teams": {"widgets": {"running": 1, "waiting": 0},
                                             "acme": {"running": 8, "waiting": 3}}}
        self.assertEqual(teams_chips(runner), [[("teams", "dim")],
                                               [("acme", "bold"), (" 8 run 3 wait", "dim")],
                                               [("widgets", "bold"), (" 1 run 0 wait", "dim")]])

    def test_a_count_that_is_not_a_number_shows_as_zero(self):
        self.assertEqual(teams_chips({"state": "live", "teams": {"-": {"running": "x"}}}),
                         [[("teams", "dim")], [("-", "bold"), (" 0 run 0 wait", "dim")]])

    def test_no_row_without_a_live_runner_with_teams(self):
        teams = {"acme": {"running": 1, "waiting": 0}}
        for runner in ({"state": "stale", "teams": teams}, {"teams": teams}, {"state": "live"},
                       {"state": "live", "teams": {}}, {"state": "live", "teams": [teams]}):
            with self.subTest(runner=runner):
                self.assertEqual(teams_chips(runner), [])


if __name__ == "__main__":
    unittest.main()
