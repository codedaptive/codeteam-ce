"""The repository top (.git or .jj) for git commands."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share/claude-hooks"))
from git_top import git_top


@pytest.mark.parametrize("marker", [".git", ".jj"])
def test_marker_at_cwd_is_top(tmp_path, marker):
    (tmp_path / "repo" / marker).mkdir(parents=True)
    assert git_top(str(tmp_path / "repo")) == str(tmp_path / "repo")


@pytest.mark.parametrize("marker", [".git", ".jj"])
def test_ancestor_marker_is_top(tmp_path, marker):
    (tmp_path / "repo" / marker).mkdir(parents=True)
    (tmp_path / "repo/docs/nested").mkdir(parents=True)
    assert git_top(str(tmp_path / "repo/docs/nested")) == str(tmp_path / "repo")


@pytest.mark.parametrize("outer,inner", [(".git", ".jj"), (".jj", ".git"),
                                          (".git", ".git"), (".jj", ".jj")])
def test_nearest_marker_wins(tmp_path, outer, inner):
    (tmp_path / "repo" / outer).mkdir(parents=True)
    (tmp_path / "repo/nested" / inner).mkdir(parents=True)
    (tmp_path / "repo/nested/docs").mkdir()
    assert git_top(str(tmp_path / "repo/nested/docs")) == str(tmp_path / "repo/nested")


def test_git_marker_file_is_accepted(tmp_path):
    (tmp_path / "repo/docs").mkdir(parents=True)
    (tmp_path / "repo/.git").write_text("gitdir: elsewhere\n")
    assert git_top(str(tmp_path / "repo/docs")) == str(tmp_path / "repo")


def test_no_marker_returns_cwd(tmp_path):
    (tmp_path / "untracked/docs").mkdir(parents=True)
    assert git_top(str(tmp_path / "untracked/docs")) == str(tmp_path / "untracked/docs")
