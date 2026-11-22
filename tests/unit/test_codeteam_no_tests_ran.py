import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_no_tests_ran import no_tests_ran


def test_test_one_no_tests():
    assert no_tests_ran(["test-one: docs: no tests"]) is True


def test_cargo_zero_tests():
    assert no_tests_ran(["test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s"]) is True


def test_pytest_no_tests():
    assert no_tests_ran(["no tests ran in 0.01s"]) is True


def test_all_skipped_pytest_leg_and_file_summary():
    assert no_tests_ran([
        "test-one: run python3 -m pytest -q -p no:cacheprovider tests/runtime/integration",
        "ssss [100%]",
        "89 skipped in 1.02s",
        "ok   tests/runtime/integration",
        "test-one: 1 passed, 0 failed",
    ]) is True


def test_decorated_skipped_summary():
    assert no_tests_ran(["==== 89 skipped in 1.02s ===="]) is True


def test_cargo_ran_in_another_leg():
    assert no_tests_ran(["test-one: zone: no tests", "test result: ok. 5 passed; 0 failed"]) is False


def test_bash_ran_after_skipped_pytest():
    assert no_tests_ran([
        "test-one: run python3 -m pytest -q tests/b",
        "89 skipped in 1.02s",
        "ok   tests/b",
        "test-one: run bash tests/a.sh",
        "ok   tests/a.sh",
        "test-one: 2 passed, 0 failed",
    ]) is False


def test_failed_script_leg_ran():
    assert no_tests_ran(["test-one: docs: no tests", "test-one: run python3 tests/unit/x.py", "FAIL tests/unit/x.py (exit 1)"]) is False


def test_pytest_passed_with_skips():
    assert no_tests_ran(["1 passed, 2 skipped in 0.1s"]) is False


def test_pytest_failed_with_skips():
    assert no_tests_ran(["1 failed, 2 skipped in 0.1s"]) is False


def test_xctest_ran():
    assert no_tests_ran(["test-one: docs: no tests", "Executed 3 tests, with 0 failures"]) is False


def test_swift_testing_ran():
    assert no_tests_ran(["test-one: zone/rust: no tests",
                         "✔ Test run with 5 tests in 2 suites passed after 0.012 seconds."]) is False


def test_empty_output():
    assert no_tests_ran([]) is False


def test_unrecognised_output():
    assert no_tests_ran(["make: nothing to be done"]) is False


def test_no_tests_must_be_a_full_test_one_line():
    assert no_tests_ran(["test-one: docs: no tests but more output"]) is False


def test_stray_skipped_count_is_no_signal():
    assert no_tests_ran(["skipping: 3 skipped by the build"]) is False
