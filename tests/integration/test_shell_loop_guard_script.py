"""share/claude-hooks/shell-loop-guard.py run as Claude Code runs it: python3 on the file, the call's JSON on stdin.
Integration: it starts a real process and imports shell_loop.py from
beside the script; decide's choices are unit-tested in tests/unit/test_shell_loop_guard.py. Skipped unless
CODETEAM_TEST_GROUP=integration."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("CODETEAM_TEST_GROUP", "unit") != "integration",
                                reason="integration group only; run with CODETEAM_TEST_GROUP=integration")

HOOK = Path(__file__).resolve().parents[2] / "share" / "claude-hooks" / "shell-loop-guard.py"


def run(stdin):
    return subprocess.run([sys.executable, "-B", str(HOOK)], input=stdin, capture_output=True, text=True, timeout=30)


def test_a_loop_is_refused_and_exit_is_0():
    done = run(json.dumps({"tool_name": "Bash", "tool_input": {"command": "for f in a; do :; done"}}))
    assert done.returncode == 0
    assert json.loads(done.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.parametrize("stdin", ["{not json", json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})])
def test_unreadable_input_and_a_plain_command_go_through(stdin):
    done = run(stdin)
    assert (done.returncode, done.stdout) == (0, "")
