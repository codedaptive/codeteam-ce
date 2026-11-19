#!/usr/bin/env python3
"""Manifest switch accepts only a stripped representation of one."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_kinds_switch import kinds_by_name


class KindsSwitchTests(unittest.TestCase):
    def test_enabled_values(self):
        for value in ("1", " 1 ", 1):
            with self.subTest(value=value):
                self.assertTrue(kinds_by_name({"CODETEAM_KINDS_BY_NAME": value}))

    def test_disabled_values_and_missing(self):
        for env in ({}, *({"CODETEAM_KINDS_BY_NAME": value} for value in ("", "0", "true", "yes", "11"))):
            with self.subTest(env=env):
                self.assertFalse(kinds_by_name(env))


if __name__ == "__main__":
    unittest.main(verbosity=2)
