"""The ancestry predicate used to exclude landings already in a work order's tree."""
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_merged_landing import merged_landing


class FakeGit:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        result = next(self.results)
        if isinstance(result, OSError):
            raise result
        return SimpleNamespace(returncode=result)


def test_ancestor_is_contained():
    git = FakeGit([0])
    assert merged_landing(git, "commit", ["tip"]) is True
    assert git.calls == [("merge-base", "--is-ancestor", "commit", "tip")]


def test_non_ancestor_is_not_contained():
    git = FakeGit([1])
    assert merged_landing(git, "commit", ["tip"]) is False
    assert git.calls == [("merge-base", "--is-ancestor", "commit", "tip")]


def test_second_tip_contains_commit():
    git = FakeGit([1, 0])
    assert merged_landing(git, "commit", iter(["first", "second"])) is True
    assert git.calls == [("merge-base", "--is-ancestor", "commit", "first"),
                         ("merge-base", "--is-ancestor", "commit", "second")]


def test_no_tips_makes_no_git_call():
    git = FakeGit([])
    assert merged_landing(git, "commit", []) is False
    assert git.calls == []


def test_oserror_from_git_propagates():
    git = FakeGit([OSError("git unavailable"), 0])
    with pytest.raises(OSError):
        merged_landing(git, "commit", ["first", "second"])
    assert git.calls == [("merge-base", "--is-ancestor", "commit", "first")]


def test_real_git_ancestor_equal_and_unrelated(tmp_path):
    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, text=True)

    def checked(*args):
        result = git(*args)
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    checked("init", "-q")
    checked("config", "user.name", "Test")
    checked("config", "user.email", "test@example.invalid")
    checked("commit", "--allow-empty", "-qm", "base")
    base = checked("rev-parse", "HEAD")
    checked("commit", "--allow-empty", "-qm", "next")
    tip = checked("rev-parse", "HEAD")
    assert merged_landing(git, base, [tip]) is True
    assert merged_landing(git, tip, [tip]) is True
    assert merged_landing(git, tip, [base]) is False
