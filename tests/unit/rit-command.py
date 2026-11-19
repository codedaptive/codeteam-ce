#!/usr/bin/env -S python3 -u
"""RIT-only command selection and quoting; the selector is exported to the whole command."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_rit_command import rit_command


def test_zone_test_one():
    assert rit_command("make zone-test-one DIR={dir} CLASS={cls}", "rit_") == (
        "export CODETEAM_RIT_SELECTOR=rit_; make zone-test-one DIR={dir} CLASS={cls} "
        "CARGO_TEST_ARGS=rit_ SWIFT_TEST_ARGS='--filter rit_'")


def test_quotes_selector():
    assert rit_command("make zone-test-one DIR={dir}", "rit a") == (
        "export CODETEAM_RIT_SELECTOR='rit a'; make zone-test-one DIR={dir} "
        "CARGO_TEST_ARGS='rit a' SWIFT_TEST_ARGS='--filter rit a'")


def test_explicit_template():
    assert rit_command("custom", "rit a", "run {selector} {dir} {zone} {cls}") == (
        "export CODETEAM_RIT_SELECTOR='rit a'; run 'rit a' {dir} {zone} {cls}")


def test_compound_template_is_exported_whole():
    assert rit_command("custom", "rit_", "cd {dir} && run {selector}; check") == (
        "export CODETEAM_RIT_SELECTOR=rit_; cd {dir} && run rit_; check")


def test_unknown_command_is_conservative():
    assert rit_command("custom {dir}", "rit_") is None


failed = 0
for name, test in list(globals().items()):
    if name.startswith("test_") and callable(test):
        try:
            test()
            print(f"PASS {name}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
print(f"{failed} failed" if failed else "all passed")
sys.exit(bool(failed))
