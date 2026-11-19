import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share/claude-hooks"))
import orc_git_paths


@pytest.mark.parametrize("sub, rest, expected", [
    ("restore", ["-s", "HEAD", "a", "--source", "other", "b", "--", "-x"], ["a", "b", "-x"]),
    ("restore", ["--pathspec-from-file", "names", "x"], ["x"]),
    ("checkout", ["-b", "branch", "HEAD", "--", "a", "-b"], ["a", "-b"]),
    ("checkout", ["branch", "dir"], ["branch", "dir"]),
    ("restore", ["--source=HEAD", "x"], ["x"]),
    ("restore", [], []),
])
def test_paths_and_option_values(monkeypatch, sub, rest, expected):
    calls = []
    def index_only(*args):
        calls.append(args)
        return False
    monkeypatch.setattr(orc_git_paths, "orc_index_only", index_only)
    assert orc_git_paths.orc_git_paths(sub, rest) == expected
    assert calls == [(sub, rest)]


def test_index_only_restore_has_no_paths(monkeypatch):
    calls = []
    def index_only(*args):
        calls.append(args)
        return True
    monkeypatch.setattr(orc_git_paths, "orc_index_only", index_only)
    assert orc_git_paths.orc_git_paths("restore", ["-S", "x"]) == []
    assert calls == [("restore", ["-S", "x"])]


def test_staged_after_separator_is_a_pathspec():
    assert orc_git_paths.orc_git_paths("restore", ["--", "--staged"]) == ["--staged"]


def test_staged_before_separator_writes_no_paths():
    assert orc_git_paths.orc_git_paths("restore", ["--staged", "x"]) == []
