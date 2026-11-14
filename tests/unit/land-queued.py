#!/usr/bin/env -S python3 -u
"""A landing step's record carries its build-queue wait apart from its seconds: zone-tool
prints the wait just before a queue job's summary line, and codeteam-land reads it from there. Nothing runs and no
file is read: the queue folder given to print_done does not exist."""
import contextlib
import importlib.machinery
import importlib.util
import io
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True


def load(name, path, quiet=False):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    if quiet:
        with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
            loader.exec_module(module)
    else:
        loader.exec_module(module)
    return module


cl = load("cl_queued", ROOT / "bin" / "codeteam-land", quiet=True)
zt = load("zt_queued", ROOT / "bin" / "zone-tool")
NO_QUEUE = Path("/nonexistent/queue")
SUMMARY = "zone-test: PASS (exit 0); record /t/.test-record.json"


def printed(job):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        zt.print_done(NO_QUEUE, job)
    return out.getvalue().splitlines()


def test_a_job_that_ran_prints_its_wait_just_before_its_summary():
    job = {"ticket": "20261113-180437-ea3aee", "submitted": 100.0, "started": 400.4, "finished": 402.0, "exit": 0,
           "result": "PASS", "record": "/t/.test-record.json"}
    lines = printed(job)
    assert lines[-2] == "zone-tool: queued 300 s, ran 2 s (job 20261113-180437-ea3aee)", lines
    assert lines[-1] == SUMMARY, lines


def test_an_answered_job_prints_no_wait():
    job = {"ticket": "t1", "submitted": 1.0, "started": 1.0, "finished": 1.0, "exit": 0, "result": "PASS",
           "answered": True, "record": "/t/.test-record.json"}
    assert not any(line.startswith("zone-tool: queued") for line in printed(job))


def test_a_job_with_no_start_time_prints_no_wait():
    job = {"ticket": "t2", "submitted": 1.0, "started": None, "finished": 5.0, "exit": 0, "result": "PASS",
           "record": "/t/.test-record.json"}
    assert not any(line.startswith("zone-tool: queued") for line in printed(job))


def test_the_wait_is_read_from_the_line_before_a_summary():
    text = f"log line\nzone-tool: queued 612 s, ran 2 s (job 20261113-180437-ea3aee)\n{SUMMARY}\n"
    assert cl.queued_seconds(text) == 612


def test_two_jobs_in_one_step_add_up():
    one = f"zone-tool: queued 10 s, ran 5 s (job a)\n{SUMMARY}\n"
    two = f"zone-tool: queued 7 s, ran 1 s (job b)\n{SUMMARY}\n"
    assert cl.queued_seconds(one + two) == 17


def test_a_wait_line_not_followed_by_a_summary_is_not_counted():
    # a test's own output can quote the line; only zone-tool's, right before its summary, counts
    assert cl.queued_seconds("zone-tool: queued 99 s, ran 1 s (job x)\nmore output\n") is None
    assert cl.queued_seconds(f"{SUMMARY}\n") is None


def test_stage2_and_recheck_rows_carry_the_wait_only_when_there_was_one():
    waited = {"name": "zone", "outcome": "PASS", "seconds": 614.04, "queued": 612}
    ran_here = {"name": "v2", "outcome": "PASS", "seconds": 3.0}
    assert cl.stage2_record([waited, ran_here]) == [
        {"step": "zone", "result": "pass", "seconds": 614.0, "queued": 612},
        {"step": "v2", "result": "pass", "seconds": 3.0}]
    row = {"M": "m", "wo": "w", "overlapping": [], "zones": ["cli"]}
    tests = cl.integration_result(row, [waited, ran_here], "now")["tests"]
    assert tests == [{"name": "zone", "result": "pass", "seconds": 614.0, "queued": 612},
                     {"name": "v2", "result": "pass", "seconds": 3.0}]


if __name__ == "__main__":
    for fn in (test_a_job_that_ran_prints_its_wait_just_before_its_summary, test_an_answered_job_prints_no_wait,
               test_a_job_with_no_start_time_prints_no_wait, test_the_wait_is_read_from_the_line_before_a_summary,
               test_two_jobs_in_one_step_add_up, test_a_wait_line_not_followed_by_a_summary_is_not_counted,
               test_stage2_and_recheck_rows_carry_the_wait_only_when_there_was_one):
        fn()
    print("all passed")
