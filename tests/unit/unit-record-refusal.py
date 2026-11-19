#!/usr/bin/env python3
"""The refusal gives enough evidence and commands to repair the landing."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_unit_record_refusal import unit_record_refusal


class UnitRecordRefusalTests(unittest.TestCase):
    def test_keys_and_commands_are_actionable(self):
        text = unit_record_refusal("work-42", "alpha", "0123456789abcdef", ["key one", "key two"],
                                   ["make first", "make second"])
        for value in ("work-42", "alpha", "0123456789", "key one", "key two",
                      "CODETEAM_KINDS_BY_NAME=1", "land again"):
            with self.subTest(value=value):
                self.assertIn(value, text)
        self.assertIn("make first", text.splitlines())
        self.assertIn("make second", text.splitlines())

    def test_unreadable_keys_are_explained(self):
        text = unit_record_refusal("work-42", "alpha", "0123456789abcdef", None, [])
        self.assertIn("could not be read", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
