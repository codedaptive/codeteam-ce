import importlib.machinery
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("zone_tool_print_done_build", str(ROOT / "bin" / "zone-tool"))
zone_tool = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
loader.exec_module(zone_tool)


@pytest.fixture
def job(tmp_path):
    return {"ticket": "job-1", "submitted": 100.0, "started": 400.4, "finished": 402.0,
            "exit": 0, "result": "PASS", "record": str(tmp_path / "record.json")}


@pytest.mark.parametrize(("build_seconds", "formatted"), [(12.6, "13"), (0, "0")])
def test_ran_job_includes_numeric_build_seconds(job, tmp_path, capsys, build_seconds, formatted):
    Path(job["record"]).write_text(json.dumps({"build_seconds": build_seconds}))
    zone_tool.print_done(tmp_path, job)
    assert capsys.readouterr().out.splitlines() == [
        f"zone-tool: queued 300 s, ran 2 s (job job-1, build {formatted} s)",
        f"zone-test: PASS (exit 0); record {job['record']}",
    ]


@pytest.mark.parametrize("record", ["missing", "unreadable", "invalid_json", "no_field", "nonnumeric"])
def test_ran_job_without_numeric_build_seconds_keeps_old_output(job, tmp_path, capsys, record):
    path = Path(job["record"])
    if record == "unreadable":
        path.mkdir()
    elif record == "invalid_json":
        path.write_text("{")
    elif record == "no_field":
        path.write_text(json.dumps({"result": "PASS"}))
    elif record == "nonnumeric":
        path.write_text(json.dumps({"build_seconds": "12"}))
    zone_tool.print_done(tmp_path, job)
    assert capsys.readouterr().out.splitlines() == [
        "zone-tool: queued 300 s, ran 2 s (job job-1)",
        f"zone-test: PASS (exit 0); record {job['record']}",
    ]


def test_answered_job_does_not_print_build_timing(job, tmp_path, capsys):
    Path(job["record"]).write_text(json.dumps({"build_seconds": 12.6}))
    job["answered"] = True
    zone_tool.print_done(tmp_path, job)
    assert capsys.readouterr().out.splitlines() == [
        f"zone-test: PASS (exit 0); answered from record {job['record']}",
    ]
