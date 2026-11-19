"""own_work_time: when a work order's tree last moved, by its own commits (D580's extraction from
patrol.stalled_work_orders). Unit tests: git is faked by patching subprocess.run."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2.own_work_time import own_work_time  # noqa: E402


def fake_git(count, ct="1700000000\n"):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=count if "rev-list" in args else ct)
    return run, calls


class OwnWorkTimeTests(unittest.TestCase):
    def test_no_base_is_none_without_asking_git(self):
        run, calls = fake_git("2\n")
        with patch("subprocess.run", side_effect=run):
            self.assertIsNone(own_work_time(Path("/tree"), ""))
        self.assertEqual(calls, [])

    def test_no_commit_of_its_own_is_none(self):
        run, _ = fake_git("0\n")
        with patch("subprocess.run", side_effect=run):
            self.assertIsNone(own_work_time(Path("/tree"), "abc"))

    def test_an_empty_count_is_none(self):
        run, _ = fake_git("")
        with patch("subprocess.run", side_effect=run):
            self.assertIsNone(own_work_time(Path("/tree"), "abc"))

    def test_own_commits_give_the_last_commit_time(self):
        run, calls = fake_git("2\n")
        with patch("subprocess.run", side_effect=run):
            self.assertEqual(own_work_time(Path("/tree"), "abc"), 1700000000.0)
        self.assertEqual(calls, [["git", "-C", "/tree", "rev-list", "--count", "abc..HEAD"],
                                 ["git", "-C", "/tree", "log", "-1", "--format=%ct"]])

    def test_git_failing_is_none(self):
        with patch("subprocess.run", side_effect=OSError("no git")):
            self.assertIsNone(own_work_time(Path("/tree"), "abc"))


if __name__ == "__main__":
    unittest.main()
