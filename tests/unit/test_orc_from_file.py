import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share/claude-hooks"))
import orc_from_file


@pytest.mark.parametrize("rest, expected", [
    ([], False),
    (["--pathspec-from-file", "paths"], True),
    (["--pathspec-from-file=paths"], True),
    (["--", "--pathspec-from-file=paths"], False),
    (["--pathspec-from-fileish=x"], False),
    (["--pathspec-from-file=paths", "--", "x"], True),
])
def test_from_file_only_before_separator(rest, expected):
    assert orc_from_file.orc_from_file(rest) is expected
