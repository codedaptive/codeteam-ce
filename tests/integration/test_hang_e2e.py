"""Integration: spec v5.2's hang rule end to end. `zone-tool test` runs a real child in a scratch git
repo with a short hang window: a silent, idle child and the process under it are stopped and recorded HUNG (exit 124,
`zone-test: HUNG:` on stderr); a child that keeps printing while idle runs past the window and passes.
Joins: bin/zone-tool's cmd_test, share/codeteam_hang.py (tree CPU from proc_pid_rusage, the window), kill_tree, the
record file and real processes. Skipped unless CODETEAM_TEST_GROUP=integration."""
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("CODETEAM_TEST_GROUP", "unit") != "integration",
                                reason="integration group only; run with CODETEAM_TEST_GROUP=integration")

HOME = Path(__file__).resolve().parents[2]
ZONE_TOOL = str(HOME / "bin" / "zone-tool")
WINDOW = 2  # seconds: CODETEAM_HANG_WINDOW for these runs; the printing child outlives it twice over


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    for args in (["init", "-q"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty",
                                   "-m", "start"]):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    return root


def zone_test(repo, *cmd):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CODETEAM_", "HERDR_"))}
    env.update(CODETEAM_HANG_WINDOW=str(WINDOW), CODETEAM_HANG_CPU_PCT="1")
    # A backstop only, far past any outcome, so a broken hang rule fails here instead of holding the run.
    return subprocess.run([ZONE_TOOL, "test", "--key", "hang-e2e", "--", *cmd], cwd=repo, env=env,
                          capture_output=True, text=True, timeout=600)


def record(repo):
    (path,) = repo.glob(".test-record-*.json")
    return json.loads(path.read_text())


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_a_silent_idle_child_is_hung_and_its_tree_is_stopped(repo):
    pidfile = repo / "grandchild.pid"
    r = zone_test(repo, "/bin/sh", "-c", f"sleep 300 & echo $! > {pidfile}; wait")
    assert r.returncode == 124, (r.returncode, r.stdout, r.stderr)
    assert "zone-test: HUNG:" in r.stderr
    rec = record(repo)
    assert (rec["result"], rec["exit"]) == ("HUNG", 124)
    assert rec["reason"].startswith("hung:")
    grandchild = int(pidfile.read_text())
    for _ in range(100):  # an orphan is reaped by launchd, not by us: give it the chance
        if not alive(grandchild):
            break
        time.sleep(0.1)
    assert not alive(grandchild), f"the sleep under the hung run (pid {grandchild}) is still running"


def test_a_child_that_keeps_printing_runs_past_the_window_and_passes(repo):
    script = "i=0; while [ $i -lt 10 ]; do echo tick $i; sleep 0.5; i=$((i+1)); done"
    r = zone_test(repo, "/bin/sh", "-c", script)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    assert "HUNG" not in r.stderr
    assert "tick 9" in r.stdout
    rec = record(repo)
    assert (rec["result"], rec["exit"], rec["reason"]) == ("PASS", 0, None)
