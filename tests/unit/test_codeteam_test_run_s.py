import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_test_run_s import test_run_s as measure


def test_only_test_steps_count_with_step_and_name():
    rows = [{"step": "tests a", "seconds": 600}, {"name": "tests b", "seconds": 360},
            {"step": "compile", "seconds": 5000}]
    assert measure(rows, lambda name: name.startswith("tests "), lambda row: row["seconds"]) == 960.0


def test_parallel_intervals_count_once():
    rows = [{"step": "test", "seconds": 600, "end": 700},
            {"name": "test", "seconds": 600, "end": 700}]
    assert measure(rows, lambda name: name == "test", lambda row: row["seconds"]) == 600.0


def test_serial_intervals_and_rows_without_end_add():
    rows = [{"step": "test", "seconds": 600, "end": 600},
            {"name": "test", "seconds": 300, "end": 900}, {"step": "test", "seconds": 60}]
    assert measure(rows, lambda name: name == "test", lambda row: row["seconds"]) == 960.0
