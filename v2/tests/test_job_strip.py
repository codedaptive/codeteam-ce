"""job_strip (work order teamslot, decision 7): the BUILDS box's one cell per job. Unit tests: the pure function
only."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2.deck.job_strip import job_strip  # noqa: E402


class JobStripTests(unittest.TestCase):
    def test_running_then_queued_one_cell_each(self):
        self.assertEqual(job_strip(2, 3, False), [("██", "green"), ("███", "faint")])

    def test_motion_sweeps_the_running_cells(self):
        self.assertEqual(job_strip(1, 0, True), [("█", "green ~sweep"), ("", "faint")])

    def test_motion_with_nothing_running_has_no_sweep(self):
        self.assertEqual(job_strip(0, 2, True), [("", "green"), ("██", "faint")])


if __name__ == "__main__":
    unittest.main()
