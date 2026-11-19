import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_file_test_rows import file_test_rows


COLOURED = ("\x1b[41m\x1b[1m FAIL \x1b[22m\x1b[49m \x1b[30m\x1b[46m engine "
            "\x1b[49m\x1b[39m __tests__/mcp-daemon.test.ts\x1b[2m > \x1b[22mmcp daemon"
            "\x1b[2m > \x1b[22mstarts one server")
SECOND = " FAIL   engine  __tests__/daemon-older-version.test.ts > a launcher > never stops a server from a newer install"


def test_one_row_per_file_in_first_appearance_order():
    tail = "\n".join([COLOURED, SECOND, " FAIL  __tests__/mcp-daemon.test.ts > mcp daemon > stops"])
    assert file_test_rows({"result": "fail", "tail": tail}, []) == [
        {"name": "__tests__/mcp-daemon.test.ts", "result": "fail", "seconds": None,
         "failing": ["__tests__/mcp-daemon.test.ts > mcp daemon > starts one server",
                     "__tests__/mcp-daemon.test.ts > mcp daemon > stops"]},
        {"name": "__tests__/daemon-older-version.test.ts", "result": "fail", "seconds": None,
         "failing": ["__tests__/daemon-older-version.test.ts > a launcher > never stops a server from a newer install"]}]


def test_each_file_is_capped_at_twenty_tests():
    tail = "\n".join(f" FAIL  src/a.test.ts > case {i}" for i in range(25))
    assert file_test_rows({"result": "fail", "tail": tail}, []) == [
        {"name": "src/a.test.ts", "result": "fail", "seconds": None, "failing": [
            "src/a.test.ts > case 0", "src/a.test.ts > case 1", "src/a.test.ts > case 2",
            "src/a.test.ts > case 3", "src/a.test.ts > case 4", "src/a.test.ts > case 5",
            "src/a.test.ts > case 6", "src/a.test.ts > case 7", "src/a.test.ts > case 8",
            "src/a.test.ts > case 9", "src/a.test.ts > case 10", "src/a.test.ts > case 11",
            "src/a.test.ts > case 12", "src/a.test.ts > case 13", "src/a.test.ts > case 14",
            "src/a.test.ts > case 15", "src/a.test.ts > case 16", "src/a.test.ts > case 17",
            "src/a.test.ts > case 18", "src/a.test.ts > case 19"]}]


def test_file_level_failure_has_no_failing_test_names():
    assert file_test_rows({"result": "fail", "tail": " FAIL  src/broken.test.ts [ src/broken.test.ts ]"}, []) == [
        {"name": "src/broken.test.ts", "result": "fail", "seconds": None, "failing": []}]


def test_open_names_that_are_not_failing_are_passes():
    assert file_test_rows({"result": "fail", "tail": SECOND},
                          ["__tests__/daemon-older-version.test.ts", "src/old.test.ts"]) == [
        {"name": "__tests__/daemon-older-version.test.ts", "result": "fail", "seconds": None,
         "failing": ["__tests__/daemon-older-version.test.ts > a launcher > never stops a server from a newer install"]},
        {"name": "src/old.test.ts", "result": "pass", "seconds": None}]


def test_hung_keeps_suite_without_passing_open_suite():
    assert file_test_rows({"result": "hung", "seconds": 42, "tail": SECOND}, ["suite", "src/old.test.ts"]) == [
        {"name": "__tests__/daemon-older-version.test.ts", "result": "fail", "seconds": None,
         "failing": ["__tests__/daemon-older-version.test.ts > a launcher > never stops a server from a newer install"]},
        {"name": "src/old.test.ts", "result": "pass", "seconds": None},
        {"name": "suite", "result": "hung", "seconds": 42}]


def test_pass_never_produces_file_rows():
    assert file_test_rows({"result": "pass", "tail": SECOND}, ["src/old.test.ts"]) == []


def test_failure_without_vitest_summary_produces_no_rows():
    assert file_test_rows({"result": "fail", "tail": " ❯  engine  __tests__/mcp-daemon.test.ts (17 tests | 8 failed) 30007ms\n   ✓ src/ok.test.ts (3 tests) 12ms"}, ["src/old.test.ts"]) == []
