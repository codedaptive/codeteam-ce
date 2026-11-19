#!/usr/bin/env -S python3 -u
"""A calling zone's RIT steps: the lane's own test gets the selector exported to the whole command."""
import shlex
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_rit_steps import rit_steps


def steps(lane, selector="rit_", roots=("a/tests",)):
    values = {"test": "make zone-test-one DIR={dir} CLASS={cls}"}
    team = SimpleNamespace(c=lambda key, default=None: values.get(key, default))
    return rit_steps(team, "/tree", "cli", selector, ["x.py"], zone_tests=lambda *a, **k: [("zit", "zit")],
                     test_folders=lambda team, tree, zone, group, files: list(roots),
                     rit_roots=lambda tree, folders, selector: folders, lane_rec=lambda team, zone: lane,
                     lane_test_key=lambda zone, group: f"key {zone} {group}", zone_tool="zt",
                     test_template="unused")


def test_compound_lane_test_is_exported_whole():
    assert steps({"test": "A && if B; then C; fi"}) == [(
        "rits cli (its lane's test)",
        "zt job submit --class land --wait 0 --key 'key cli integration rits' -- "
        "sh -c 'export CODETEAM_RIT_SELECTOR=rit_; A && if B; then C; fi'")]


def test_selector_is_quoted_inside_the_shell_command():
    [(_, command)] = steps({"test": "A"}, selector="rit a")
    assert shlex.split(command)[-3:] == ["sh", "-c", "export CODETEAM_RIT_SELECTOR='rit a'; A"]


def test_without_a_lane_test_each_root_runs_the_rit_command():
    assert steps({}) == [(
        "rits cli (a/tests)",
        "export CODETEAM_RIT_SELECTOR=rit_; make zone-test-one DIR=a/tests CLASS=land "
        "CARGO_TEST_ARGS=rit_ SWIFT_TEST_ARGS='--filter rit_'")]


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
