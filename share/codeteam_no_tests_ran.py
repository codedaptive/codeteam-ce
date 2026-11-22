"""no_tests_ran: does a test run's whole output say no test ran, or that every test it found was skipped?

zone-tool records such a run, when it exits 0, as NO TESTS rather than PASS: a green record that ran nothing proves
nothing (codeteam-jj #4860; the rule follows jj's bin/zone-tool _ran_no_tests, with the all-skipped case added).

One run holds several legs (zone.mk's ZONE_TEST runs test-one on $(ZONE), then on $(ZONE)/rust, which usually finds
no tests), so one empty leg never outweighs another that ran.
"""
import re

# A count above 0 passed or failed (cargo's and pytest's summaries), XCTest's "Executed N tests" or Swift Testing's
# "Test run with N tests ... passed/failed", with N of 1 or more.
RAN = re.compile(r"\b[1-9]\d* (passed|failed)\b|\bExecuted [1-9]\d* tests?\b|\bTest run with [1-9]\d* tests?\b")
# test-one's own lines (share/codeteam_run_planned.py): a leg starts, a leg ends, or its target held no test.
# Its "test-one: N passed, M failed" counts files, not tests, so it never shows a test ran (jj counts it; then a
# pytest leg with every test skipped still read as a pass, jj #5562).
LEG = "test-one: run "
LEG_END = re.compile(r"ok   .+|FAIL .+ \(exit -?\d+\)")
TEST_ONE_EMPTY = re.compile(r"test-one: .+: no tests")
CARGO_ZERO = re.compile(r"\b0 passed; 0 failed\b")
# pytest's summary ("89 skipped in 1.02s", also inside its "====" rule); a stray "3 skipped" elsewhere is no signal.
ALL_SKIPPED = re.compile(r"\b[1-9]\d* skipped\b.* in [\d.]+s\b")


def _script_leg_ran(lines: list[str]) -> bool:
    """A test-one leg that is not pytest finished (ok or FAIL): the script itself was the test. A pytest leg's own
    summary says whether a test ran, so its ok line does not."""
    in_script_leg = False
    for line in lines:
        if line.startswith(LEG):
            in_script_leg = "-m pytest" not in line
        elif in_script_leg and LEG_END.fullmatch(line):
            return True
    return False


def _no_tests_signal(line: str) -> bool:
    return bool(TEST_ONE_EMPTY.fullmatch(line) or "no tests ran" in line
                or ("test result:" in line and CARGO_ZERO.search(line)) or ALL_SKIPPED.search(line))


def no_tests_ran(lines: list[str]) -> bool:
    """True when no line shows a test ran and at least one line is a no-tests signal: test-one's "<dir>: no tests",
    pytest's "no tests ran", a cargo "test result:" line reading "0 passed; 0 failed", or a pytest summary with
    skipped above 0 (with no passed or failed, every test it found was skipped)."""
    stripped = [line.strip() for line in lines]
    if _script_leg_ran(stripped) or any(not line.startswith("test-one:") and RAN.search(line) for line in stripped):
        return False
    return any(_no_tests_signal(line) for line in stripped)
