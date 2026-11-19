#!/usr/bin/env -S python3 -u
"""Parse zone-tool job run times and cached zone-test answers for landing records."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("codeteam_ran", ROOT / "share" / "codeteam_ran.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

SUMMARY = "zone-test: PASS (exit 0); record /tmp/record.json"


def test_empty_output_has_no_run_time():
    assert module.ran_seconds("") is None


def test_one_job_reports_its_run_time():
    assert module.ran_seconds(f"zone-tool: queued 612 s, ran 7 s (job a)\n{SUMMARY}\n") == 7


def test_several_jobs_add_their_run_times():
    assert module.ran_seconds(f"zone-tool: queued 10 s, ran 5 s (job a)\n{SUMMARY}\n"
                              f"zone-tool: queued 7 s, ran 1 s (job b)\n{SUMMARY}\n") == 6


def test_quoted_job_without_immediate_summary_does_not_count():
    assert module.ran_seconds(f"zone-tool: queued 99 s, ran 4 s (job x)\nother output\n{SUMMARY}\n") is None


def test_exact_code_record_means_no_run():
    assert module.ran_seconds("zone-test: PASS at 14:23 already recorded for this exact code; not run again\n") == 0


def test_unchanged_inputs_record_means_no_run():
    assert module.ran_seconds("zone-test: PASS at 14:23 already recorded; nothing these tests touch has changed since; not run again\n") == 0


def test_answered_job_record_means_no_run():
    assert module.ran_seconds("zone-test: PASS (exit 0); answered from record /tmp/record.json\n") == 0


def test_job_time_takes_precedence_over_cached_marker():
    assert module.ran_seconds(f"zone-tool: queued 20 s, ran 8 s (job a)\n{SUMMARY}\n"
                              "zone-test: PASS at 14:23 already recorded for this exact code; not run again\n") == 8


def test_plain_output_has_no_run_time():
    assert module.ran_seconds("all passed\n") is None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("all passed")
