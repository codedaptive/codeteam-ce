import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_run_union import run_union


def seconds(row):
    return row["ran"]


def test_overlapping_intervals_count_once():
    assert run_union([{"end": 600, "ran": 600}, {"end": 700, "ran": 600}], seconds) == 700


def test_adjacent_intervals_add():
    assert run_union([{"end": 300, "ran": 300}, {"end": 600, "ran": 300}], seconds) == 600


def test_old_rows_add_to_overlapping_intervals():
    assert run_union([{"end": 100, "ran": 100}, {"end": 150, "ran": 100}, {"ran": 40}], seconds) == 190


def test_empty_rows_have_zero_duration():
    assert run_union([], seconds) == 0


def test_disjoint_and_nested_intervals():
    assert run_union([{"end": 400, "ran": 100}, {"end": 100, "ran": 100},
                      {"end": 90, "ran": 20}], seconds) == 200
