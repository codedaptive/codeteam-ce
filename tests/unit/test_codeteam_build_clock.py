import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))


@pytest.fixture
def clock():
    from codeteam_build_clock import BuildClock

    return BuildClock()


def test_cargo_finished_durations_add(clock):
    clock.line(1, "    Finished `test` profile [unoptimized + debuginfo] target(s) in 3.5s\n")
    clock.line(4, "    Finished `dev` profile [unoptimized + debuginfo] target(s) in 1m 02s")
    assert clock.seconds(200) == 65.5


def test_cargo_ignores_finished_lines_without_targets(clock):
    clock.line(1, "Finished upload in 2.0s")
    assert clock.seconds(2) == 0.0


def test_cargo_counts_finished_target_duration(clock):
    clock.line(1, "    Finished `test` profile [unoptimized + debuginfo] target(s) in 2.0s")
    assert clock.seconds(2) == 2.0


def test_record_rounds_build_seconds(clock):
    clock.line(1.0, "Command line invocation:")
    clock.line(2.0, "    xcodebuild build-for-testing")
    clock.line(161.04, "** TEST BUILD SUCCEEDED **")
    assert clock.record(200.0) == {"build_seconds": 160.0}


def test_record_empty_run_has_zero_build_seconds(clock):
    assert clock.record(30.0) == {"build_seconds": 0.0}


def test_cargo_hours_minutes_and_seconds(clock):
    clock.line(1, "    Finished `test` profile [unoptimized + debuginfo] target(s) in 1h 2m 3s")
    assert clock.seconds(2) == 3723.0


def test_cargo_older_finished_format(clock):
    clock.line(1, "    Finished test [unoptimized + debuginfo] target(s) in 3.21s")
    assert clock.seconds(2) == 3.21


def test_swiftpm_build_complete(clock):
    clock.line(5, "Build complete! (12.34s)\n")
    assert clock.seconds(20) == 12.34


def test_xcode_build_for_testing_excludes_test_without_building(clock):
    clock.line(5, "Command line invocation:\n")
    clock.line(6, "\n")
    clock.line(7, "    /usr/bin/xcodebuild -scheme App build-for-testing\n")
    clock.line(165, "** TEST BUILD SUCCEEDED **\n")
    clock.line(170, "Command line invocation:")
    clock.line(171, "    /usr/bin/xcodebuild test-without-building")
    clock.line(175, "Testing started")
    assert clock.seconds(200) == 160.0


def test_xcode_test_action_stops_at_testing_started(clock):
    clock.line(2, "Command line invocation:")
    clock.line(3, "    /usr/bin/xcodebuild test -scheme App")
    clock.line(50, "Testing started on device")
    assert clock.seconds(100) == 48.0


@pytest.mark.parametrize("closing", [
    "** TEST BUILD SUCCEEDED **", "** TEST BUILD FAILED **",
    "** BUILD SUCCEEDED **", "** BUILD FAILED **", "Testing started on device",
])
def test_xcode_first_closing_line_ends_build(clock, closing):
    clock.line(10, "Command line invocation:")
    clock.line(11, "    xcodebuild build")
    clock.line(20, f"  {closing}  \n")
    clock.line(40, "** BUILD SUCCEEDED **")
    assert clock.seconds(50) == 10.0


def test_xcode_multiple_build_phases_add(clock):
    clock.line(2, "Command line invocation:")
    clock.line(3, "    xcodebuild build")
    clock.line(12, "** BUILD FAILED **")
    clock.line(20, "Command line invocation:")
    clock.line(21, "    xcodebuild build-for-testing")
    clock.line(35, "** TEST BUILD FAILED **")
    assert clock.seconds(50) == 25.0


def test_xcode_open_phase_ends_at_run_end(clock):
    clock.line(10, "Command line invocation:")
    clock.line(11, "    xcodebuild build")
    assert clock.seconds(30) == 20.0


def test_xcode_only_next_nonblank_line_selects_action(clock):
    clock.line(5, "Command line invocation:")
    clock.line(6, "  \n")
    clock.line(7, "    xcodebuild clean")
    clock.line(8, "    xcodebuild build")
    clock.line(20, "** BUILD SUCCEEDED **")
    assert clock.seconds(30) == 0.0


def test_pytest_and_plain_output_have_no_build_time(clock):
    clock.line(1, "================ test session starts ================")
    clock.line(20, "12 passed in 19.00s\n")
    clock.line(21, "ordinary output")
    assert clock.seconds(30) == 0.0


def test_empty_run_has_no_build_time(clock):
    assert clock.seconds(30) == 0.0
