#!/usr/bin/env python3
"""Unit tests for the newest write time in a folder's top two levels."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
import codeteam_newest_write
from codeteam_newest_write import newest_write


class NewestWriteTests(unittest.TestCase):
    OLD = 1704000000
    NEW = 1704067200

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.t = Path(self.temp.name) / "t"
        self.entry = self.t / "entry"
        self.inner = self.entry / "inner"
        self.deep = self.inner / "deep"
        self.deep.mkdir(parents=True)
        (self.deep / "file").write_text("x")
        self.paths = [self.deep / "file", self.deep, self.inner, self.entry, self.t]

    def stamp(self, newest=None):
        """Every path written at OLD, then newest (if given) at NEW: children first, so a folder's own mtime stays."""
        for p in self.paths:
            os.utime(p, (self.OLD, self.OLD))
        if newest is not None:
            os.utime(newest, (self.OLD, self.NEW))

    def test_the_folder_itself_newest(self):
        self.stamp(self.t)
        self.assertEqual(newest_write(self.t), self.NEW)

    def test_an_entry_newest(self):
        self.stamp(self.entry)
        self.assertEqual(newest_write(self.t), self.NEW)

    def test_an_entrys_entry_newest(self):
        self.stamp(self.inner)
        self.assertEqual(newest_write(self.t), self.NEW)

    def test_a_write_below_the_top_two_levels_is_not_seen(self):
        self.stamp(self.deep / "file")
        self.assertEqual(newest_write(self.t), self.OLD)

    def test_at_most_list_cap_entries_are_read_per_folder(self):
        c = Path(self.temp.name) / "c"
        for i in range(5):
            for j in range(5):
                (c / f"d{i}" / f"f{j}").mkdir(parents=True)
        seen = set()
        real = Path.lstat

        def lstat(p):
            seen.add(p)
            return real(p)

        with patch.object(codeteam_newest_write, "LIST_CAP", 2), patch.object(Path, "lstat", lstat):
            newest_write(c)
        # c, 2 of its 5 entries and 2 of the 5 entries of each of those.
        self.assertEqual(len(seen), 7)

    def test_a_missing_folder_counts_as_written_now(self):
        self.assertEqual(newest_write(Path(self.temp.name) / "gone"), float("inf"))


if __name__ == "__main__":
    unittest.main()
