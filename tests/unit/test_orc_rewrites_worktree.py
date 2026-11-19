import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share/claude-hooks"))
import orc_rewrites_worktree


@pytest.mark.parametrize("sub, rest, expected", [
    ("clean", [], True),
    ("clean", ["-fd"], True),
    ("clean", ["--dry-run"], False),
    ("clean", ["-fdn"], False),
    ("clean", ["--name"], True),
    ("clean", ["--", "-n"], True),
    ("reset", [], False),
    ("reset", ["--hard"], True),
    ("reset", ["--merge"], True),
    ("reset", ["--keep"], True),
    ("reset", ["--", "--hard"], False),
    ("checkout", ["--hard"], False),
])
def test_rewriting_commands_and_options(sub, rest, expected):
    assert orc_rewrites_worktree.orc_rewrites_worktree(sub, rest) is expected
