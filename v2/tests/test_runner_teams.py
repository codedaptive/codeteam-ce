"""runner_teams (work order teamslot, decision 7): the per-team job counts the deck takes from queue-runner.json's
"teams" object. Unit tests: the pure function only."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2.deck.runner_teams import runner_teams  # noqa: E402


class RunnerTeamsTests(unittest.TestCase):
    def test_valid_entries_are_kept_as_they_are(self):
        self.assertEqual(runner_teams({"acme": {"running": 8, "waiting": 3}, "-": {"running": 0, "waiting": 1}}),
                         {"acme": {"running": 8, "waiting": 3}, "-": {"running": 0, "waiting": 1}})

    def test_only_the_valid_entries_are_returned(self):
        self.assertEqual(runner_teams({"widgets": {"running": 1, "waiting": 0}, "acme": {"running": -1, "waiting": 2}}),
                         {"widgets": {"running": 1, "waiting": 0}})

    def test_a_value_that_is_not_an_object_gives_none(self):
        for value in (None, [], [{"running": 1, "waiting": 0}], "acme", 1, 1.5, True):
            with self.subTest(value=value):
                self.assertIsNone(runner_teams(value))

    def test_an_empty_object_gives_an_empty_dict(self):
        self.assertEqual(runner_teams({}), {})

    def test_bool_counts_are_dropped(self):
        self.assertEqual(runner_teams({"ok": {"running": 0, "waiting": 0}, "run": {"running": True, "waiting": 0},
                                       "wait": {"running": 0, "waiting": False}}),
                         {"ok": {"running": 0, "waiting": 0}})

    def test_negative_counts_are_dropped(self):
        self.assertEqual(runner_teams({"ok": {"running": 2, "waiting": 5}, "run": {"running": -1, "waiting": 0},
                                       "wait": {"running": 0, "waiting": -3}}),
                         {"ok": {"running": 2, "waiting": 5}})

    def test_missing_or_non_int_counts_are_dropped(self):
        self.assertEqual(runner_teams({"ok": {"running": 1, "waiting": 1}, "no_run": {"waiting": 2},
                                       "no_wait": {"running": 1}, "float": {"running": 1.0, "waiting": 0},
                                       "text": {"running": 0, "waiting": "1"}, "null": {"running": None, "waiting": 0}}),
                         {"ok": {"running": 1, "waiting": 1}})

    def test_values_that_are_not_objects_are_dropped(self):
        self.assertEqual(runner_teams({"ok": {"running": 0, "waiting": 4}, "int": 4, "list": [1, 2], "null": None,
                                       "text": "running"}),
                         {"ok": {"running": 0, "waiting": 4}})

    def test_keys_that_are_not_strings_are_dropped(self):
        self.assertEqual(runner_teams({"ok": {"running": 3, "waiting": 0}, 7: {"running": 1, "waiting": 1},
                                       None: {"running": 1, "waiting": 1}}),
                         {"ok": {"running": 3, "waiting": 0}})

    def test_other_fields_of_an_entry_are_left_out(self):
        self.assertEqual(runner_teams({"acme": {"running": 2, "waiting": 1, "slot": "x"}}),
                         {"acme": {"running": 2, "waiting": 1}})


if __name__ == "__main__":
    unittest.main()
