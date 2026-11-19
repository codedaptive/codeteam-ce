#!/usr/bin/env python3
"""Unit tests for stale target cleanup."""

import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import ModuleType
import unittest
from unittest.mock import Mock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
tree_module = ModuleType("codeteam_order_trees")
tree_module.order_trees = Mock()
with patch.dict(sys.modules, {"codeteam_order_trees": tree_module}):
    from codeteam_stale_target import sweep_stale_targets


class StaleTargetsTests(unittest.TestCase):
    NOW = 1704067200
    OLD = NOW - 7200

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "team space"
        self.root.mkdir()
        self.tree = self.root / "wo" / "lane" / "ticket"
        self.target = self.tree / "target"
        (self.target / "debug" / "deps").mkdir(parents=True)
        (self.target / "debug" / "deps" / "artifact").write_text("old")
        self.cargo = self.tree / "cargo-target"
        self.cargo.mkdir()
        (self.cargo / "keep").write_text("cargo output")
        for path in (self.target / "debug" / "deps" / "artifact", self.target / "debug" / "deps",
                     self.target / "debug", self.target):
            os.utime(path, (self.OLD, self.OLD))
        (self.tree / "fresh-file").write_text("active tree")
        os.utime(self.tree, (self.NOW - 60, self.NOW - 60))
        self.manifest = self.base / "demo.toml"
        self.manifest.write_text(f'worktree_root = "{self.root}"\n[env]\nCODETEAM_CARGO_TARGET = "1"\n')
        self.queue = self.base / "queue"
        self.queue.mkdir()
        self.queued = Mock(return_value=set())
        self.runs = Mock(return_value=None)
        self.popen = Mock()
        tree_module.order_trees.reset_mock(return_value=True, side_effect=True)
        tree_module.order_trees.return_value = {self.tree}
        self.output = io.StringIO()
        self.tz = patch.dict(os.environ, {"TZ": "UTC"})
        self.tz.start()
        time.tzset()
        self.addCleanup(self.restore_tz)

    def restore_tz(self):
        self.tz.stop()
        time.tzset()

    def sweep(self, manifests=None):
        with contextlib.redirect_stdout(self.output):
            return sweep_stale_targets([self.manifest] if manifests is None else manifests, self.queue,
                                       self.queued, self.runs, 200.0, now=self.NOW, popen=self.popen)

    def test_stale_target_is_removed_despite_fresh_tree_and_cargo_output_stays(self):
        result = self.sweep()
        self.assertEqual(result, [f"removed {self.tree}/target (beside cargo-target; no build queued or running)"])
        self.assertEqual(self.output.getvalue(), f"2024-01-01 00:00:00 disk (200 GB free): removed {self.tree}/target "
                                                  "(beside cargo-target; no build queued or running)\n")
        self.assertFalse(self.target.exists())
        self.assertTrue(self.tree.is_dir())
        self.assertEqual((self.cargo / "keep").read_text(), "cargo output")
        self.assertEqual((self.root / ".trash" / "20240101-000000-ticket-target" / "debug" / "deps" /
                          "artifact").read_text(), "old")

    def test_missing_queue_folder_removes_nothing_and_reads_no_manifest(self):
        self.queue = self.base / "no-queue"
        self.assertEqual(self.sweep(), [])
        self.assertTrue((self.target / "debug" / "deps" / "artifact").is_file())
        self.assertFalse((self.root / ".trash").exists())
        tree_module.order_trees.assert_not_called()
        self.runs.assert_not_called()
        self.popen.assert_not_called()

    def test_queued_tree_is_kept(self):
        self.queued.return_value = {os.path.realpath(self.tree)}
        self.assertEqual(self.sweep(), [])
        self.assertTrue(self.target.is_dir())
        self.popen.assert_not_called()

    def test_other_checkout_queue_keeps_tree(self):
        checkout = self.base / "other-checkout"
        other_queue = checkout / "run" / "queue"
        self.runs.return_value = (checkout, checkout / "teams" / "demo.toml")
        self.queued.side_effect = lambda q: {os.path.realpath(self.tree)} if q == other_queue else set()
        self.assertEqual(self.sweep(), [])
        self.queued.assert_any_call(other_queue)
        self.runs.assert_called_with("demo")
        self.assertTrue(self.target.is_dir())
        self.popen.assert_not_called()

    def test_recent_target_directory_is_kept(self):
        os.utime(self.target, (self.NOW - 60, self.NOW - 60))
        self.assertEqual(self.sweep(), [])
        self.assertTrue(self.target.is_dir())

    def test_recent_entry_two_levels_down_is_kept(self):
        os.utime(self.target / "debug" / "deps", (self.NOW - 60, self.NOW - 60))
        self.assertEqual(self.sweep(), [])
        self.assertTrue(self.target.is_dir())

    def test_target_without_cargo_target_is_kept(self):
        (self.cargo / "keep").unlink()
        self.cargo.rmdir()
        self.assertEqual(self.sweep(), [])
        self.assertTrue(self.target.is_dir())
        self.popen.assert_not_called()

    def test_symlink_target_is_kept(self):
        original = self.tree / "actual-target"
        self.target.rename(original)
        self.target.symlink_to(original, target_is_directory=True)
        self.assertEqual(self.sweep(), [])
        self.assertTrue(self.target.is_symlink())
        self.assertTrue(original.is_dir())
        self.popen.assert_not_called()

    def test_manifests_without_opt_in_are_left_alone(self):
        for env in ("", '[env]\nCODETEAM_CARGO_TARGET = "0"\n'):
            with self.subTest(env=env):
                self.manifest.write_text(f'worktree_root = "{self.root}"\n{env}')
                tree_module.order_trees.reset_mock()
                self.queued.reset_mock()
                self.runs.reset_mock()
                self.assertEqual(self.sweep(), [])
                self.assertTrue(self.target.is_dir())
                tree_module.order_trees.assert_not_called()
                self.runs.assert_not_called()
                self.popen.assert_not_called()

    def test_one_background_removal_per_root_with_quoted_trash_path(self):
        second = self.root / "wo" / "lane" / "second"
        (second / "target").mkdir(parents=True)
        (second / "cargo-target").mkdir()
        os.utime(second / "target", (self.OLD, self.OLD))
        tree_module.order_trees.return_value = {self.tree, second}
        result = self.sweep()
        self.assertCountEqual(result, [
            f"removed {self.tree}/target (beside cargo-target; no build queued or running)",
            f"removed {second}/target (beside cargo-target; no build queued or running)",
        ])
        self.popen.assert_called_once_with(["sh", "-c", f"rm -rf '{self.root}/.trash'/*"],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                           start_new_session=True)
        self.assertTrue((second / "cargo-target").is_dir())

    def test_each_root_that_loses_a_target_gets_one_background_removal(self):
        other = self.base / "other space"
        other_tree = other / "wo" / "lane" / "other"
        (other_tree / "target").mkdir(parents=True)
        (other_tree / "cargo-target").mkdir()
        os.utime(other_tree / "target", (self.OLD, self.OLD))
        second_manifest = self.base / "other.toml"
        second_manifest.write_text(f'worktree_root = "{other}"\n[env]\nCODETEAM_CARGO_TARGET = "1"\n')
        tree_module.order_trees.side_effect = lambda root: {self.tree} if root == self.root else {other_tree}
        self.assertEqual(len(self.sweep([self.manifest, second_manifest])), 2)
        self.assertCountEqual(self.popen.call_args_list, [
            call(["sh", "-c", f"rm -rf '{self.root}/.trash'/*"], stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL, start_new_session=True),
            call(["sh", "-c", f"rm -rf '{other}/.trash'/*"], stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL, start_new_session=True),
        ])


if __name__ == "__main__":
    unittest.main()
