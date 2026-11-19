#!/usr/bin/env -S python3 -u
"""Landings already merged into a work order do not cause a recheck or conflict attribution."""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

queue_dir = tempfile.TemporaryDirectory(prefix="land-queue-")
os.environ["CODETEAM_QUEUE_DIR"] = str(Path(queue_dir.name) / "queue")
ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_recheck_in_tree", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
with patch("subprocess.run", return_value=SimpleNamespace(stdout="", stderr="", returncode=0)):
    loader.exec_module(cl)


class RecheckInTree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="land-in-tree-")
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.repo = root / "repo"
        self.repo.mkdir()
        self.team_dir = root / "team"
        self.team_dir.mkdir()
        self.team = SimpleNamespace(dir=self.team_dir, repo=self.repo, zones={"A": ["A"]},
                                    c=lambda key, default=None: default)
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("commit", "--allow-empty", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")
        (self.repo / "A").mkdir()
        (self.repo / "A" / "landed.txt").write_text("landed work\n")
        self.git("add", "A/landed.txt")
        self.git("commit", "-qm", "landed X")
        self.old = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "--detach", self.base)
        (self.repo / "A").mkdir(exist_ok=True)
        (self.repo / "A" / "work.txt").write_text("work order\n")
        self.git("add", "A/work.txt")
        self.git("commit", "-qm", "work order")
        self.without_x = self.git("rev-parse", "HEAD")
        self.git("merge", "-q", "--no-ff", "-m", "merge landed X", self.old)
        self.with_x = self.git("rev-parse", "HEAD")
        row = {"hash": self.old, "range": f"{self.base}..{self.old}", "wos": ["landed-X"]}
        (self.team_dir / "landed.log").write_text(json.dumps(row) + "\n")

    def git(self, *args):
        result = subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def entry(self, tip):
        return {"wo": "work", "tip": tip, "base": self.base, "zones": ["A"]}

    def test_landing_in_entry_tip_does_not_recheck_or_write_row(self):
        self.assertFalse(cl.landing_recheck(self.team, self.entry(self.with_x), self.old, self.with_x))
        log = self.team_dir / "recheck.jsonl"
        self.assertFalse(log.exists() and log.read_text())

    def test_landing_absent_from_tip_rechecks_and_names_work_order(self):
        self.assertTrue(cl.landing_recheck(self.team, self.entry(self.without_x), self.old, self.without_x))
        rows = (self.team_dir / "recheck.jsonl").read_text().splitlines()
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0])["overlapping"], ["landed-X"])

    def test_landing_in_second_set_member_does_not_recheck(self):
        entry = self.entry(self.without_x)
        entry["tips"] = [["work", self.without_x], ["work-two", self.with_x]]
        self.assertFalse(cl.landing_recheck(self.team, entry, self.old, self.with_x))
        log = self.team_dir / "recheck.jsonl"
        self.assertFalse(log.exists() and log.read_text())

    def test_conflicting_landings_omits_landing_in_tip(self):
        self.assertEqual(cl.conflicting_landings(self.team, self.base, self.old, ["A/landed.txt"]), ["landed-X"])
        self.assertEqual(cl.conflicting_landings(self.team, self.base, self.old, ["A/landed.txt"],
                                               tips=[self.with_x]), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
