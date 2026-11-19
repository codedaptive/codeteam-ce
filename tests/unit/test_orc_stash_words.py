import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share/claude-hooks"))
import orc_stash_words


@pytest.mark.parametrize("rest, expected", [
    ([], ("", [])),
    (["--", "x", "-y"], ("", ["x", "-y"])),
    (["push", "-m", "message", "a", "--", "b", "-x"], ("push", ["a", "b", "-x"])),
    (["--message", "msg", "push", "--pathspec-from-file", "names", "x"], ("push", ["x"])),
    (["save", "message", "--", "x"], ("save", [])),
    (["pop", "stash@{0}"], ("pop", [])),
    (["list"], ("list", [])),
])
def test_stash_action_and_paths(rest, expected):
    assert orc_stash_words.orc_stash_words(rest) == expected
