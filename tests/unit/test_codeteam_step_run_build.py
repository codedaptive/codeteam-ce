import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "share"))
loader = importlib.machinery.SourceFileLoader("cl_build_seconds", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)

from codeteam_test_run_s import test_run_s as measure_test_run_s


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        pytest.param({"ran": 449, "build": 175, "seconds": 817, "queued": 360}, 274, id="ran-less-build"),
        pytest.param({"seconds": 100, "queued": 10, "build": 30}, 60, id="fallback-less-build"),
        pytest.param({"ran": 10, "build": 12, "seconds": 20}, 0, id="ran-clamped"),
        pytest.param({"seconds": 20, "queued": 10, "build": 12}, 0, id="fallback-clamped"),
        pytest.param({"ran": 7, "seconds": 9}, 7, id="old-ran"),
        pytest.param({"seconds": 100, "queued": 10}, 90, id="old-fallback"),
        pytest.param({"ran": 7, "seconds": 9, "build": None}, 7, id="unknown-build"),
    ],
)
def test_step_run_seconds_excludes_build(row, expected):
    assert cl.step_run_seconds(row) == expected


def test_queue_fields_carries_build_and_existing_fields():
    assert cl.queue_fields({"queued": 2, "ran": 10, "build": 3, "start": 11, "end": 21}) == {
        "queued": 2, "ran": 10, "build": 3, "start": 11, "end": 21}


def test_queue_fields_keeps_zero_build():
    assert cl.queue_fields({"build": 0}) == {"build": 0}


def test_queue_fields_omits_absent_build():
    assert cl.queue_fields({"ran": 7}) == {"ran": 7}


def test_stage2_rows_carry_build_including_zero():
    results = [{"name": "job", "outcome": "PASS", "seconds": 20, "queued": 2, "ran": 10, "build": 3},
               {"name": "zero", "outcome": "PASS", "seconds": 2, "build": 0},
               {"name": "old", "outcome": "PASS", "seconds": 3}]
    assert cl.stage2_record(results) == [
        {"step": "job", "result": "pass", "seconds": 20, "queued": 2, "ran": 10, "build": 3},
        {"step": "zero", "result": "pass", "seconds": 2, "build": 0},
        {"step": "old", "result": "pass", "seconds": 3}]


def test_integration_rows_carry_build_including_zero():
    row = {"M": "m", "wo": "w", "overlapping": [], "zones": ["cli"]}
    results = [{"name": "job", "outcome": "PASS", "seconds": 20, "queued": 2, "ran": 10, "build": 3},
               {"name": "zero", "outcome": "PASS", "seconds": 2, "build": 0},
               {"name": "old", "outcome": "PASS", "seconds": 3}]
    assert cl.integration_result(row, results, "now")["tests"] == [
        {"name": "job", "result": "pass", "seconds": 20, "queued": 2, "ran": 10, "build": 3},
        {"name": "zero", "result": "pass", "seconds": 2, "build": 0},
        {"name": "old", "result": "pass", "seconds": 3}]


def test_slow_flag_uses_run_less_build_for_threshold():
    rows = [{"step": "tests a (x)", "ran": 600, "build": 400, "end": 1000},
            {"step": "tests b (y)", "ran": 700, "build": 100, "end": 2000}]
    assert cl.slow_tests_flag(rows) is None


def test_slow_flag_reports_build_only_when_present():
    rows = [{"step": "tests a (x)", "ran": 1000, "build": 25.25, "queued": 3, "end": 1000},
            {"name": "tests b (y)", "ran": 30, "build": 0, "end": 2000},
            {"step": "tests c (z)", "ran": 20, "end": 3000}]
    assert cl.slow_tests_flag(rows) == {
        "total_s": 1024.8, "limit_s": 900, "steps": [
            {"step": "tests a (x)", "run_s": 974.8, "queued_s": 3, "build_s": 25.2},
            {"step": "tests b (y)", "run_s": 30, "queued_s": 0, "build_s": 0},
            {"step": "tests c (z)", "run_s": 20, "queued_s": 0}]}


def test_r26_measure_excludes_build_from_stage2_and_recheck_rows():
    rows = [{"step": "tests a (x)", "ran": 600, "build": 400, "end": 1000},
            {"name": "tests b (y)", "ran": 700, "build": 100, "end": 2000},
            {"step": "compile a (x)", "ran": 5000, "build": 0, "end": 8000}]
    assert measure_test_run_s(rows, cl.is_test_step, cl.step_run_seconds) == 800
