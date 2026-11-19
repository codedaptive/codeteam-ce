"""class_chips (work order teamslot, decision 7): the BUILDS box's class chips. Unit tests: the pure function, with
stand-in readers for the renderer's number and dicts."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2.deck.class_chips import class_chips  # noqa: E402


def number(x):
    return "?" if not isinstance(x, int) else str(x)


def dicts(items):
    return [x for x in items if isinstance(x, dict)] if isinstance(items, list) else []


class ClassChipsTests(unittest.TestCase):
    def test_running_over_ceiling(self):
        self.assertEqual(class_chips([{"class": "dev", "running": [{}, {}], "ceiling": 4}], number, dicts),
                         [[("dev", "teal bold"), (" 2/4", "dim")]])

    def test_a_ceiling_of_zero_is_infinity(self):
        self.assertEqual(class_chips([{"class": "full", "running": [], "ceiling": 0}], number, dicts),
                         [[("full", "teal bold"), (" 0/∞", "dim")]])

    def test_running_counts_only_what_dicts_keeps(self):
        self.assertEqual(class_chips([{"class": "pre", "running": [{}, "x", 3], "ceiling": 2}], number, dicts),
                         [[("pre", "teal bold"), (" 1/2", "dim")]])

    def test_a_class_with_no_name_or_ceiling(self):
        self.assertEqual(class_chips([{}], number, dicts), [[("?", "teal bold"), (" 0/?", "dim")]])

    def test_one_chip_per_class_in_order(self):
        chips = class_chips([{"class": "full", "ceiling": 0}, {"class": "dev", "ceiling": 3}], number, dicts)
        self.assertEqual([chip[0][0] for chip in chips], ["full", "dev"])


if __name__ == "__main__":
    unittest.main()
