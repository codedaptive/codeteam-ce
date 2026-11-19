import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_failure_lines import FAILURE_LINES, failure_lines


@pytest.mark.parametrize("line", [
    "FAILED ZONES: a b",
    "FAILED MODULES: x",
    "test a::b ... FAILED",
    "\x1b[41m\x1b[1m FAIL \x1b[22m\x1b[49m \x1b[30m\x1b[46m engine \x1b[49m\x1b[39m __tests__/mcp-daemon.test.ts\x1b[2m > \x1b[22mmcp daemon\x1b[2m > \x1b[22mstarts one server",
    " FAIL   engine  __tests__/daemon-older-version.test.ts > a launcher > never stops a server from a newer install",
    " FAIL  src/a.test.ts > group > case one",
    " FAIL  src/broken.test.ts [ src/broken.test.ts ]",
    " FAIL   engine  src/broken.test.ts [ src/broken.test.ts ]",
    "\x1b[41m\x1b[1m FAIL \x1b[22m\x1b[49m \x1b[30m\x1b[46m engine \x1b[49m\x1b[39m src/broken.test.ts\x1b[2m [ src/broken.test.ts ]\x1b[22m",
    " FAIL  src/broken.test.ts",
    " FAIL   engine  src/broken.test.ts",
])
def test_failure_line_is_matched_and_preserved(line):
    assert re.search(FAILURE_LINES, line) is not None
    assert failure_lines(line) == line + "\n"


@pytest.mark.parametrize("line", [
    " ❯  engine  __tests__/mcp-daemon.test.ts (17 tests | 8 failed) 30007ms",
    "     \x1b[33m\x1b[2m✓\x1b[22m\x1b[39m returns FAILED when indexAll throws SQLITE_CONSTRAINT \x1b[33m 3537\x1b[2mms\x1b[22m\x1b[39m",
    "error: 2 tests FAILED in this run",
    "FAIL: test_x (mod.Case)",
    "FAIL tests zone (12 s)",
    "   ✓ src/ok.test.ts (3 tests) 12ms",
    "",
])
def test_non_failure_line_is_not_selected(line):
    assert re.search(FAILURE_LINES, line) is None
    assert failure_lines(line) == ""


def test_only_last_400_matching_lines_are_kept_in_order():
    text = "\n".join(f"test suite::case_{i:03d} ... FAILED\nnot a failure" for i in range(450))
    expected = "".join(f"test suite::case_{i:03d} ... FAILED\n" for i in range(50, 450))
    assert failure_lines(text) == expected


def test_pattern_avoids_python_specific_character_escapes():
    for escape in (r"\s", r"\S", r"\d", r"\x"):
        assert escape not in FAILURE_LINES
