import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share/claude-hooks"))
import orc_index_only


@pytest.mark.parametrize("sub, rest, expected", [
    ("restore", [], False),
    ("restore", ["--staged"], True),
    ("restore", ["-S"], True),
    ("restore", ["-S", "--worktree"], False),
    ("restore", ["--staged", "-W"], False),
    ("checkout", ["--staged"], False),
    ("restore", ["--", "--staged"], False),
    ("restore", ["-s", "--staged"], False),
    ("restore", ["--source", "--staged", "x"], False),
    ("restore", ["--pathspec-from-file", "--staged"], False),
    ("restore", ["-s", "HEAD", "--staged"], True),
    ("restore", ["--staged", "--", "--worktree"], True),
    ("restore", ["--staged", "--source", "--worktree"], True),
])
def test_only_staged_restore_without_worktree(sub, rest, expected):
    assert orc_index_only.orc_index_only(sub, rest) is expected
