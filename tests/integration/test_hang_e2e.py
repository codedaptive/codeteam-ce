"""Integration (D281): spec v5.2's hang rule end to end (D314). `zone-tool test` runs a real child in a scratch git
repo with a short hang window: a silent, idle child is stopped and recorded HUNG (exit 124, `zone-test: HUNG:` on
stderr); a child that keeps printing while idle runs past the window and passes. That the process under a hung run is
gone afterwards takes launchd reaping the orphan, a live OS service, so it is validation:
tests/validation/hang-orphan-reaped.py (rule 11, S-33; codeteam-jj #4671).
Joins: bin/zone-tool's cmd_test, share/codeteam_hang.py (tree CPU from proc_pid_rusage, the window), kill_tree, the
record file and real processes. Skipped unless CODETEAM_TEST_GROUP=integration."""
import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("CODETEAM_TEST_GROUP", "unit") != "integration",
                                reason="integration group only (D281); run with CODETEAM_TEST_GROUP=integration")

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


def test_a_silent_idle_child_is_hung_and_recorded(repo):
    r = zone_test(repo, "/bin/sh", "-c", "sleep 300 & wait")
    assert r.returncode == 124, (r.returncode, r.stdout, r.stderr)
    assert "zone-test: HUNG:" in r.stderr
    rec = record(repo)
    assert (rec["result"], rec["exit"]) == ("HUNG", 124)
    assert rec["reason"].startswith("hung:")


def test_a_child_that_keeps_printing_runs_past_the_window_and_passes(repo):
    script = "i=0; while [ $i -lt 10 ]; do echo tick $i; sleep 0.5; i=$((i+1)); done"
    r = zone_test(repo, "/bin/sh", "-c", script)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    assert "HUNG" not in r.stderr
    assert "tick 9" in r.stdout
    rec = record(repo)
    assert (rec["result"], rec["exit"], rec["reason"]) == ("PASS", 0, None)
