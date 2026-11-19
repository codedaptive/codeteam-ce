#!/usr/bin/env -S python3 -u
"""A RIT step's selector reaches every part of a compound test command under a real sh.

An `X=v cmd` prefix binds only the first simple command: `X=v A && B` runs B without X. The lane's test runs inside
`zone-tool job submit ... -- sh -c '<command>'`; a stand-in zone-tool here runs what follows `--`.

An integration test, not a RIT: it joins two share/ modules and a real shell, inside one kit, and no
second kit (zone-tool is the stand-in). share/ is the orchestrator's, with no lane of its own, so its integration tests are in
codeteam's integration group, tests/integration, beside the landing tool's.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_rit_command import rit_command
from codeteam_rit_steps import rit_steps

W = Path(tempfile.mkdtemp(prefix="rit-selector-export-"))
ZONE_TOOL = W / "zone-tool"
ZONE_TOOL.write_text('#!/bin/sh\nwhile [ "$1" != "--" ]; do shift; done\nshift\nexec "$@"\n')
ZONE_TOOL.chmod(0o755)
COMPOUND = 'true && echo "first=${CODETEAM_RIT_SELECTOR-unset}" && sh -c \'echo "child=${CODETEAM_RIT_SELECTOR-unset}"\''
ENV = {k: v for k, v in os.environ.items() if k != "CODETEAM_RIT_SELECTOR"}


def output(command):
    return subprocess.run(command, shell=True, cwd=W, env=ENV, capture_output=True, text=True, check=True).stdout


def test_lane_test_step_exports_the_selector_to_every_part():
    team = SimpleNamespace(c=lambda key, default=None: default)
    [(_, command)] = rit_steps(team, str(W), "cli", "rit_", ["x.py"], zone_tests=None, test_folders=None,
                               rit_roots=None, lane_rec=lambda team, zone: {"test": COMPOUND},
                               lane_test_key=lambda zone, group: "key", zone_tool=str(ZONE_TOOL),
                               test_template="unused")
    assert output(command) == "first=rit_\nchild=rit_\n"


def test_compound_rit_test_exports_the_selector_to_every_part():
    assert output(rit_command("unused", "rit_", COMPOUND)) == "first=rit_\nchild=rit_\n"


failed = 0
for name, test in list(globals().items()):
    if name.startswith("test_") and callable(test):
        try:
            test()
            print(f"PASS {name}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
for leftover in sorted(W.iterdir()):
    leftover.unlink()
W.rmdir()
print(f"{failed} failed" if failed else "all passed")
sys.exit(bool(failed))
