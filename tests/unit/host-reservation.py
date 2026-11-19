#!/usr/bin/env -S python3 -u
"""HostReservation holds a validation host for a capped time. A unit test: a temp folder
stands in for codeteam's run/ folder and every time is passed in."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_host_reservation import HostReservation  # noqa: E402

T0 = 1_000_000.0


class HostReservationTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run_dir = Path(tmp.name)
        self.r = HostReservation(self.run_dir)

    def test_take_holds_until_its_minutes_run_out(self):
        self.r.take("valhost", 30, "lab", "S-208 timed run", T0)
        self.assertEqual(self.r.held("valhost", T0 + 1799)["by"], "lab")
        self.assertIsNone(self.r.held("valhost", T0 + 1800))

    def test_file_names_the_holder_reason_and_end(self):
        self.r.take("valhost", 20, "lab", "S-129 rate run", T0)
        row = json.loads((self.run_dir / "host-reservations" / "valhost.json").read_text())
        self.assertEqual(row, {"host": "valhost", "by": "lab", "reason": "S-129 rate run", "since": T0,
                               "until": T0 + 1200})

    def test_minutes_outside_the_cap_are_refused(self):
        for minutes in (0, -5, 91):
            with self.assertRaises(ValueError, msg=minutes):
                self.r.take("valhost", minutes, "lab", "x", T0)
        self.r.take("valhost", 90, "lab", "x", T0)
        self.assertIsNone(self.r.held("valhost", T0 + 90 * 60))

    def test_another_holder_is_refused_while_it_holds_and_not_after(self):
        self.r.take("valhost", 10, "lab", "timed", T0)
        with self.assertRaises(ValueError) as caught:
            self.r.take("valhost", 10, "bolt", "mine", T0 + 60)
        self.assertIn("reserved by lab", str(caught.exception))
        self.assertEqual(self.r.take("valhost", 10, "bolt", "mine", T0 + 600)["by"], "bolt")

    def test_same_holder_replaces_its_end_time(self):
        self.r.take("valhost", 10, "lab", "timed", T0)
        self.r.take("valhost", 5, "lab", "shorter", T0 + 60)
        self.assertIsNone(self.r.held("valhost", T0 + 60 + 300))

    def test_release_by_holder_ends_it_and_another_cannot(self):
        self.r.take("valhost", 10, "lab", "timed", T0)
        self.assertFalse(self.r.release("valhost", "bolt", T0 + 1))
        self.assertIsNotNone(self.r.held("valhost", T0 + 1))
        self.assertTrue(self.r.release("valhost", "lab", T0 + 1))
        self.assertIsNone(self.r.held("valhost", T0 + 1))
        self.assertTrue(self.r.release("valhost", "lab", T0 + 2))   # nothing held: nothing to refuse

    def test_hosts_are_separate(self):
        self.r.take("valhost", 10, "lab", "timed", T0)
        self.assertIsNone(self.r.held("mini", T0))

    def test_unreadable_file_holds_nothing(self):
        (self.run_dir / "host-reservations").mkdir()
        (self.run_dir / "host-reservations" / "valhost.json").write_text("{not json")
        self.assertIsNone(self.r.held("valhost", T0))

    def test_a_host_name_with_a_path_in_it_is_refused(self):
        for host in ("../x", "a/b", "", ".hidden"):
            with self.assertRaises(ValueError, msg=host):
                self.r.take(host, 10, "lab", "x", T0)


if __name__ == "__main__":
    result = unittest.main(exit=False).result
    sys.exit(0 if result.wasSuccessful() else 1)
