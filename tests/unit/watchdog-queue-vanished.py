#!/usr/bin/env python3
"""Unit test: the watchdog's queue sweep skips a build-queue job file that is gone by the time it is read.

The build queue prunes a finished job's file once its retention time has passed (codeteam-buildq prune), so a file the
sweep lists can be gone a moment later. Before
the fix, sweep_queue read the file's age outside its try, and the FileNotFoundError ended the whole queue sweep
(run/watchdog.log, 11-09 20:4x, 11-11 22:5x, 11-13 14:31). A dangling symlink stands in for that file: it is listed,
and reading it fails as a removed file does, with no timing involved."""

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[2] / "bin" / "codeteam-watchdog"


def load_watchdog():
    loader = importlib.machinery.SourceFileLoader("watchdog_queue_under_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    with (patch("sys.dont_write_bytecode", True),
          contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO())):
        loader.exec_module(module)
    module.notify = lambda *a: None
    return module


class VanishedJobFileTests(unittest.TestCase):
    def setUp(self):
        self.watchdog = load_watchdog()
        self.tmp = tempfile.TemporaryDirectory(prefix="queue-vanished-")
        self.queue = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def sweep(self):
        with (patch("subprocess.run", side_effect=AssertionError("no job should be cancelled")),
              patch("os.kill", side_effect=AssertionError("no job should be stopped")),
              contextlib.redirect_stdout(io.StringIO())):
            return self.watchdog.sweep_queue(self.queue)

    def test_a_job_file_gone_before_it_is_read_is_skipped(self):
        (self.queue / "20261113-082155-aab2dd.json").symlink_to(self.queue / "pruned.json")
        self.assertEqual(self.sweep(), [])

    def test_the_other_jobs_are_still_swept(self):
        (self.queue / "20261113-082155-aab2dd.json").symlink_to(self.queue / "pruned.json")
        (self.queue / "20261113-082156-bbbbbb.json").write_text(json.dumps({
            "ticket": "20261113-082156-bbbbbb", "kind": "slot", "state": "queued", "pid": os.getpid(),
            "command": ["cargo", "check"], "worktree": "/w/a", "submitted": 1.0}))
        seen = []
        self.watchdog.alive = lambda pid: seen.append(pid) or True
        self.assertEqual(self.sweep(), [])
        self.assertEqual(seen, [os.getpid()], "the live queued job beside the gone one was looked at")


if __name__ == "__main__":
    unittest.main()
