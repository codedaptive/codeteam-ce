import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_vitest_failures import vitest_failures


RAW = "\x1b[41m\x1b[1m FAIL \x1b[22m\x1b[49m \x1b[30m\x1b[46m engine \x1b[49m\x1b[39m __tests__/mcp-daemon.test.ts\x1b[2m > \x1b[22mmcp daemon\x1b[2m > \x1b[22mstarts one server"
LABELED = " FAIL   engine  __tests__/daemon-older-version.test.ts > a launcher > never stops a server from a newer install"
UNLABELED = " FAIL  src/a.test.ts > group > case one"


@pytest.mark.parametrize(("line", "expected"), [
    (RAW, [("__tests__/mcp-daemon.test.ts", "__tests__/mcp-daemon.test.ts > mcp daemon > starts one server")]),
    (LABELED, [("__tests__/daemon-older-version.test.ts", "__tests__/daemon-older-version.test.ts > a launcher > never stops a server from a newer install")]),
    (UNLABELED, [("src/a.test.ts", "src/a.test.ts > group > case one")]),
])
def test_test_failure_with_color_or_optional_project(line, expected):
    assert vitest_failures(line) == expected


@pytest.mark.parametrize("line", [
    " FAIL  src/broken.test.ts [ src/broken.test.ts ]",
    " FAIL   engine  src/broken.test.ts [ src/broken.test.ts ]",
    " FAIL  src/broken.test.ts",
    " FAIL   engine  src/broken.test.ts",
])
def test_file_level_failure_with_optional_project(line):
    assert vitest_failures(line) == [("src/broken.test.ts", None)]


def test_deduplicates_pairs_in_first_appearance_order():
    text = "\n".join([UNLABELED, LABELED, UNLABELED, " FAIL  src/a.test.ts > group > case two", LABELED])
    assert vitest_failures(text) == [
        ("src/a.test.ts", "src/a.test.ts > group > case one"),
        ("__tests__/daemon-older-version.test.ts", "__tests__/daemon-older-version.test.ts > a launcher > never stops a server from a newer install"),
        ("src/a.test.ts", "src/a.test.ts > group > case two"),
    ]


@pytest.mark.parametrize("line", [
    " ❯  engine  __tests__/mcp-daemon.test.ts (17 tests | 8 failed) 30007ms",
    "     \x1b[33m\x1b[2m✓\x1b[22m\x1b[39m returns FAILED when indexAll throws SQLITE_CONSTRAINT \x1b[33m 3537\x1b[2mms\x1b[22m\x1b[39m",
    "   ✓ src/ok.test.ts (3 tests) 12ms",
    "FAIL: test_x (mod.Case)",
    "FAIL tests zone (12 s)",
    "error: 2 tests FAILED in this run",
    "test a::b ... FAILED",
    "FAILED tests/x.py::test_y",
    "",
])
def test_non_vitest_lines_are_ignored(line):
    assert vitest_failures(line) == []
