#!/usr/bin/env python3
"""clean_idle skips a work order tree that is not a git work tree and tells the orchestrator once, and queue-run's
idle clean never ends the runner (codeteam-jj #4406, D497: wo/orc/r37-test-kinds held only .codegraph/,
`git log` failed there, out() died, and launchd restarted queue-run into the same exit for hours). A unit test
(rule 11): git, the clock and the team are fakes; the only real thing is a temp folder standing in for the tree."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

HOME = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl", str(HOME / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader("cl", loader)
cl = importlib.util.module_from_spec(spec)
loader.exec_module(cl)

NOT_GIT = SimpleNamespace(returncode=128, stdout="", stderr="fatal: not a git repository (or any of the parent "
                                                            "directories): .git")


class FakeTeam:
    def __init__(self, root):
        self.dir = root
        (root / "wo").mkdir()
        self.saved, self.told = [], []

    def c(self, key, default=None):
        return default

    def save_wo(self, rec):
        self.saved.append(dict(rec))
        (self.dir / "wo" / f"{rec['wo']}.json").write_text(json.dumps(rec))

    def notify(self, to, kind, text):
        self.told.append((to, kind, text))


class CleanIdleNotGitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.team = FakeTeam(root)
        self.tree = root / "trees" / "r37-test-kinds"
        (self.tree / ".codegraph").mkdir(parents=True)
        (root / "wo" / "r37-test-kinds.json").write_text(json.dumps({"wo": "r37-test-kinds", "tree": str(self.tree)}))

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_tree_that_is_not_a_git_work_tree_is_skipped_and_told_once(self):
        with patch.object(cl, "git", return_value=NOT_GIT) as git, patch.object(cl, "now", return_value="T1"), \
                patch.object(cl, "process_cwds", return_value=[]):
            cl.clean_idle(self.team)
            cl.clean_idle(self.team)
        self.assertEqual(len(self.team.told), 1, "told once, not every pass")
        to, kind, text = self.team.told[0]
        self.assertEqual((to, kind), ("orc", "NOTE"))
        self.assertIn("r37-test-kinds", text)
        self.assertIn("not a git work tree", text)
        self.assertIn("not a git repository", text)
        self.assertEqual(self.team.saved, [{"wo": "r37-test-kinds", "tree": str(self.tree), "not_a_git_tree": "T1"}])
        self.assertTrue(all(call.args[1:3] == ("log", "-1") for call in git.call_args_list),
                        "nothing but the failed log runs in that tree: no status, no make zone-clean")


class QueueMaintenanceTests(unittest.TestCase):
    def test_a_clean_idle_that_exits_does_not_end_the_runner(self):
        team = SimpleNamespace()
        err = io.StringIO()
        with patch.object(cl, "prune_queue"), patch.object(cl, "features_due_locked"), \
                patch.object(cl, "clean_idle", side_effect=SystemExit(1)), contextlib.redirect_stderr(err):
            house, clean = cl.queue_maintenance(team, False, 0.0, 0.0)
        self.assertGreater(clean, 0.0, "the idle clean still counts as run, so it is not retried every pass")
        self.assertIn("clean_idle: SystemExit", err.getvalue())

    def test_a_clean_idle_that_raises_does_not_end_the_runner(self):
        err = io.StringIO()
        with patch.object(cl, "prune_queue"), patch.object(cl, "features_due_locked"), \
                patch.object(cl, "clean_idle", side_effect=OSError("disk")), contextlib.redirect_stderr(err):
            cl.queue_maintenance(SimpleNamespace(), False, 0.0, 0.0)
        self.assertIn("clean_idle: OSError: disk", err.getvalue())


if __name__ == "__main__":
    result = unittest.main(exit=False).result
    sys.exit(0 if result.wasSuccessful() else 1)
