#!/usr/bin/env -S python3 -u
"""Choose integration test or RIT steps without changing zone order."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_reached_zone_steps import reached_zone_steps


def zit(zone):
    return [(f"zit {zone}", f"test {zone}")]


def rits(zone):
    return [(f"rit {zone}", f"select {zone}")]


def test_without_selector_all_zits():
    assert reached_zone_steps(["b", "a", "c"], {"a"}, None, zit, rits) == [
        ("zit b", "test b"), ("zit a", "test a"), ("zit c", "test c")]


def test_with_selector_changed_zits_and_other_rits():
    assert reached_zone_steps(["b", "a", "c"], {"a", "outside"}, "rit_", zit, rits) == [
        ("rit b", "select b"), ("zit a", "test a"), ("rit c", "select c")]


def test_empty_steps_are_not_replaced():
    assert reached_zone_steps(["b", "a"], {"a"}, "rit_", zit, lambda zone: []) == [("zit a", "test a")]


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
