#!/usr/bin/env python3
"""clean_idle skips its whole pass when the processes' working folders cannot be read (D599): without them nobody
inside could not be told, so no tree is cleaned, saved or reported, and the pass frees 0. A unit test (rule 11): lsof,
git, the clean and the team are fakes; the only real thing is a temp folder standing in for the tree."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HOME = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl", str(HOME / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader("cl", loader)
cl = importlib.util.module_from_spec(spec)
loader.exec_module(cl)


class FakeTeam:
    def __init__(self, root):
        self.dir = root
        (root / "wo").mkdir()
        self.saved, self.told = [], []

    def c(self, key, default=None):
        return default

    def save_wo(self, rec):
        self.saved.append(dict(rec))

    def notify(self, to, kind, text):
        self.told.append((to, kind, text))


class CleanIdleNoCwdsTests(unittest.TestCase):
    def test_unreadable_process_cwds_skip_the_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            team = FakeTeam(root)
            tree = root / "trees" / "idle"
            (tree / ".codegraph").mkdir(parents=True)
            (root / "wo" / "idle.json").write_text(json.dumps({"wo": "idle", "tree": str(tree)}))
            (root / "wo" / "done.landed.json").write_text(json.dumps({"wo": "done", "tree": str(tree)}))
            err = io.StringIO()
            with patch.object(cl, "process_cwds", return_value=None), patch.object(cl, "git") as git, \
                    patch.object(cl, "clean_idle_tree") as clean, patch.object(cl, "save_record") as save, \
                    contextlib.redirect_stderr(err):
                freed = cl.clean_idle(team)
            self.assertEqual(freed, 0)
            clean.assert_not_called()
            git.assert_not_called()
            save.assert_not_called()
            self.assertEqual((team.saved, team.told), ([], []))
            self.assertIn("pass skipped", err.getvalue())
            self.assertEqual(json.loads((root / "wo" / "done.landed.json").read_text()), {"wo": "done", "tree": str(tree)})


if __name__ == "__main__":
    result = unittest.main(exit=False).result
    sys.exit(0 if result.wasSuccessful() else 1)
