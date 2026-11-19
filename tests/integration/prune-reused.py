#!/usr/bin/env python3
"""Integration tests (with the real stale_copies and newest_write) for pruning idle reused landing trees."""

import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_prune_reused import prune_reused_trees


class PruneReusedTests(unittest.TestCase):
    NOW = 1704067200
    OLD = NOW - 200000
    NEWER = NOW - 100000
    RECENT = NOW - 3600
    A = "0123456789abcdef"
    B = "fedcba9876543210"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "team space"
        self.tree = self.root / "land" / "itest"
        self.tree.mkdir(parents=True)
        self.manifest = self.base / "demo.toml"
        self.manifest.write_text(f'worktree_root = "{self.root}"\n[land]\nenabled = true\n')
        self.queue = self.base / "queue"
        self.queue.mkdir()
        self.queued = Mock(return_value=set())
        self.runs = Mock(return_value=None)
        self.clones = Mock(return_value={"itest": self.tree})
        self.held = Mock(return_value=set())
        self.popen = Mock()

    def prune(self, manifests=None, dry_run=False):
        with contextlib.redirect_stdout(io.StringIO()):
            return prune_reused_trees([self.manifest] if manifests is None else manifests, self.queue,
                                      self.queued, self.runs, self.clones, self.held,
                                      now=self.NOW, dry_run=dry_run, popen=self.popen)

    def copies(self, output):
        deps = self.tree / output / "debug" / "deps"
        deps.mkdir(parents=True)
        old = [deps / f"libfoo-{self.A}.rlib", deps / f"foo-{self.A}.d"]
        new = [deps / f"libfoo-{self.B}.rlib", deps / f"foo-{self.B}.d"]
        for paths, mtime in ((old, self.OLD), (new, self.NEWER)):
            for path, data in zip(paths, (b"abc", b"de")):
                path.write_bytes(data)
                os.utime(path, (self.OLD, mtime))
        return old, new

    def test_removes_old_copies_from_both_output_roots_and_counts_bytes(self):
        old_target, new_target = self.copies("target")
        old_cargo, new_cargo = self.copies("cargo-target")
        self.assertEqual(self.prune(), [f"pruned {self.tree}: 4 files in 2 old copies, "
                                        "0 incremental folders, 10 bytes freed"])
        for path in old_target + old_cargo:
            self.assertFalse(os.path.lexists(path))
        for path in new_target + new_cargo:
            self.assertTrue(path.exists())
        self.popen.assert_not_called()

    def test_old_incremental_folder_is_trashed_but_recent_descendant_keeps_other(self):
        incremental = self.tree / "target" / "debug" / "incremental"
        old = incremental / "old"
        recent = incremental / "recent"
        for folder in (old, recent):
            (folder / "nested").mkdir(parents=True)
            (folder / "nested" / "object").write_bytes(b"1234")
            for path in (folder / "nested" / "object", folder / "nested", folder):
                os.utime(path, (self.OLD, self.OLD))
        os.utime(recent / "nested" / "object", (self.RECENT, self.RECENT))
        self.assertEqual(self.prune(), [f"pruned {self.tree}: 0 files in 0 old copies, "
                                        "1 incremental folders, 4 bytes freed"])
        self.assertFalse(os.path.lexists(old))
        self.assertTrue(recent.exists())
        self.popen.assert_called_once_with(["sh", "-c", f"rm -rf '{self.root}/.trash'/*"],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                           start_new_session=True)

    def test_queued_clone_is_untouched(self):
        old, new = self.copies("target")
        self.queued.return_value = {os.path.realpath(self.tree)}
        self.assertEqual(self.prune(), [])
        self.assertTrue(all(path.exists() for path in old + new))
        self.popen.assert_not_called()

    def test_manifest_held_clone_is_untouched(self):
        old, new = self.copies("target")
        self.held.return_value = {(os.path.realpath(self.manifest), "itest")}
        self.assertEqual(self.prune(), [])
        self.assertTrue(all(path.exists() for path in old + new))
        self.popen.assert_not_called()

    def test_wildcard_held_clone_is_untouched(self):
        old, new = self.copies("target")
        self.held.return_value = {("*", "itest")}
        self.assertEqual(self.prune(), [])
        self.assertTrue(all(path.exists() for path in old + new))
        self.popen.assert_not_called()

    def test_missing_queue_returns_without_reading_manifests(self):
        old, _ = self.copies("target")
        self.queue = self.base / "missing-queue"
        manifest = Mock(spec=Path)
        self.assertEqual(self.prune([manifest]), [])
        manifest.read_text.assert_not_called()
        self.queued.assert_not_called()
        self.runs.assert_not_called()
        self.clones.assert_not_called()
        self.assertTrue(all(path.exists() for path in old))
        self.popen.assert_not_called()

    def test_no_manifests_returns_empty(self):
        self.assertEqual(self.prune([]), [])
        self.clones.assert_not_called()
        self.popen.assert_not_called()

    def test_unreadable_manifest_is_skipped(self):
        self.assertEqual(self.prune([self.base / "missing.toml"]), [])
        self.clones.assert_not_called()
        self.popen.assert_not_called()

    def test_missing_other_checkout_queue_skips_the_team(self):
        old, new = self.copies("target")
        checkout = self.base / "other"
        self.runs.return_value = (checkout, checkout / "teams" / "demo.toml")
        self.assertEqual(self.prune(), [])
        self.assertTrue(all(path.exists() for path in old + new))
        self.popen.assert_not_called()

    def test_dry_run_reports_counts_and_bytes_without_removing_or_spawning(self):
        old, new = self.copies("target")
        self.assertEqual(self.prune(dry_run=True), [f"would prune {self.tree}: 2 files in 1 old copies, "
                                                    "0 incremental folders, 5 bytes"])
        self.assertTrue(all(path.exists() for path in old + new))
        self.assertFalse((self.root / ".trash").exists())
        self.popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
