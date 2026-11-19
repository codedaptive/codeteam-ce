#!/usr/bin/env python3
"""Unit tests for work-order tree discovery."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_order_trees import order_trees


class OrderTreesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.records = self.root / "land" / "wo"
        self.records.mkdir(parents=True)

    def record(self, name, value):
        (self.records / name).write_text(json.dumps(value))

    def test_readable_records_name_trees_even_outside_work_order_directory(self):
        tree = self.root / "elsewhere" / "tree"
        self.record("active.json", {"tree": str(tree)})
        self.assertEqual(order_trees(self.root), {tree})

    def test_landed_retired_invalid_and_missing_tree_records_are_skipped(self):
        for name in ("done.landed.json", "old.retired.json"):
            self.record(name, {"tree": str(self.root / name)})
        (self.records / "broken.json").write_text("{")
        self.record("missing.json", {"other": "value"})
        self.assertEqual(order_trees(self.root), set())

    def test_only_two_level_directories_with_git_entry_are_discovered(self):
        work = self.root / "wo" / "lane"
        valid_file = work / "file-git"
        valid_dir = work / "dir-git"
        for tree in (valid_file, valid_dir, work / "no-git"):
            tree.mkdir(parents=True)
        (valid_file / ".git").write_text("gitdir: temp\n")
        (valid_dir / ".git").mkdir()
        (work / "not-directory").write_text("file")
        (work / "no-git" / "nested" / ".git").mkdir(parents=True)
        self.assertEqual(order_trees(self.root), {valid_file, valid_dir})

    def test_land_clones_are_not_listed_unless_recorded(self):
        itest = self.root / "land" / "itest"
        validate = self.root / "land" / "validate"
        for tree in (itest, validate):
            (tree / ".git").mkdir(parents=True)
        self.assertEqual(order_trees(self.root), set())
        self.record("clone.json", {"tree": str(itest)})
        self.assertEqual(order_trees(self.root), {itest})


if __name__ == "__main__":
    unittest.main()
