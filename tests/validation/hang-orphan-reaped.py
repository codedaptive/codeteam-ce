#!/usr/bin/env -S python3 -u
"""Validation (a live OS service is in no zone): once `zone-tool test` stops a hung run, the process
under it is gone, which takes launchd reaping the orphan. Measure: the grandchild's pid is dead within 10 s of the
run's end; threshold from the hang rule (a hung run's tree is stopped). Split from
tests/integration/test_hang_e2e.py, which keeps the HUNG outcome and its record."""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ZONE_TOOL = str(Path(__file__).resolve().parents[2] / "bin" / "zone-tool")
WINDOW = 2  # seconds: CODETEAM_HANG_WINDOW for this run


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_the_process_under_a_hung_run_is_gone_afterwards():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        for args in (["init", "-q"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty",
                                       "-m", "start"]):
            subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
        pidfile = repo / "grandchild.pid"
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CODETEAM_", "HERDR_"))}
        env.update(CODETEAM_HANG_WINDOW=str(WINDOW), CODETEAM_HANG_CPU_PCT="1")
        r = subprocess.run([ZONE_TOOL, "test", "--key", "hang-orphan", "--", "/bin/sh", "-c",
                            f"sleep 300 & echo $! > {pidfile}; wait"], cwd=repo, env=env, capture_output=True,
                           text=True, timeout=600)
        assert r.returncode == 124, (r.returncode, r.stdout, r.stderr)
        grandchild = int(pidfile.read_text())
        for _ in range(100):
            if not alive(grandchild):
                break
            time.sleep(0.1)
        assert not alive(grandchild), f"the sleep under the hung run (pid {grandchild}) is still running"


if __name__ == "__main__":
    try:
        test_the_process_under_a_hung_run_is_gone_afterwards()
        print("  PASS test_the_process_under_a_hung_run_is_gone_afterwards\nall passed")
    except Exception as ex:
        print(f"  FAIL test_the_process_under_a_hung_run_is_gone_afterwards: {type(ex).__name__}: {ex}\n1 failed")
        sys.exit(1)
