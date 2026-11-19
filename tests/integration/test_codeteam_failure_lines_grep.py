import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("CODETEAM_TEST_GROUP", "unit") != "integration",
                                reason="integration group only; run with CODETEAM_TEST_GROUP=integration")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_failure_lines import FAILURE_LINES, failure_lines


def test_grep_and_python_select_the_same_failure_lines(tmp_path):
    raw = "\x1b[41m\x1b[1m FAIL \x1b[22m\x1b[49m \x1b[30m\x1b[46m engine \x1b[49m\x1b[39m __tests__/mcp-daemon.test.ts\x1b[2m > \x1b[22mmcp daemon\x1b[2m > \x1b[22mstarts one server"
    colored_file = "\x1b[41m\x1b[1m FAIL \x1b[22m\x1b[49m \x1b[30m\x1b[46m engine \x1b[49m\x1b[39m src/broken.test.ts\x1b[2m [ src/broken.test.ts ]\x1b[22m"
    text = "\n".join([
        " ❯  engine  __tests__/mcp-daemon.test.ts (17 tests | 8 failed) 30007ms",
        "FAILED ZONES: a b",
        "     \x1b[33m\x1b[2m✓\x1b[22m\x1b[39m returns FAILED when indexAll throws SQLITE_CONSTRAINT \x1b[33m 3537\x1b[2mms\x1b[22m\x1b[39m",
        raw,
        " FAIL   engine  __tests__/daemon-older-version.test.ts > a launcher > never stops a server from a newer install",
        " FAIL  src/a.test.ts > group > case one",
        "error: 2 tests FAILED in this run",
        " FAIL  src/broken.test.ts [ src/broken.test.ts ]",
        " FAIL   engine  src/broken.test.ts [ src/broken.test.ts ]",
        colored_file,
        " FAIL  src/broken.test.ts",
        " FAIL   engine  src/broken.test.ts",
        "FAIL: test_x (mod.Case)",
        "FAIL tests zone (12 s)",
        "   ✓ src/ok.test.ts (3 tests) 12ms",
        "FAILED MODULES: x",
        "test a::b ... FAILED",
    ]) + "\n"
    expected = "\n".join([
        "FAILED ZONES: a b",
        raw,
        " FAIL   engine  __tests__/daemon-older-version.test.ts > a launcher > never stops a server from a newer install",
        " FAIL  src/a.test.ts > group > case one",
        " FAIL  src/broken.test.ts [ src/broken.test.ts ]",
        " FAIL   engine  src/broken.test.ts [ src/broken.test.ts ]",
        colored_file,
        " FAIL  src/broken.test.ts",
        " FAIL   engine  src/broken.test.ts",
        "FAILED MODULES: x",
        "test a::b ... FAILED",
    ]) + "\n"
    path = tmp_path / "validation.log"
    path.write_text(text, encoding="utf-8")
    result = subprocess.run(["grep", "-hE", FAILURE_LINES, str(path)], check=True, capture_output=True, text=True)
    assert result.stdout == expected
    assert failure_lines(text) == expected
