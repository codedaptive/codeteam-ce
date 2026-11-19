import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def zone_tool(monkeypatch):
    name = "zone_tool_settled_env"
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / "bin" / "zone-tool"))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    loader.exec_module(module)
    return module


def job(state):
    return {"ticket": "T", "kind": "run", "class": "dev", "state": state, "submitted": 1,
            "key": "k", "command": [], "worktree": "/scratch", "test_flags": [], "record": None,
            "env": {"JOBENV_FAKE": "x"}}


def read(q):
    return json.loads((q / "T.json").read_text())


@pytest.mark.parametrize("state", ["done", "broken"])
def test_update_job_settled_state_writes_empty_env(zone_tool, tmp_path, state):
    (tmp_path / "T.json").write_text(json.dumps(job("running")))
    zone_tool.update_job(tmp_path, "T", state=state, reason="example")
    saved = read(tmp_path)
    assert saved["state"] == state
    assert saved["env"] == {}
    assert saved["reason"] == "example"


def test_cancel_queued_job_writes_empty_env(zone_tool, tmp_path, monkeypatch, capsys):
    (tmp_path / "T.json").write_text(json.dumps(job("queued")))
    monkeypatch.setenv("CODETEAM_QUEUE_DIR", str(tmp_path))
    assert zone_tool.cmd_job_cancel(["T"]) == 0
    assert capsys.readouterr().out == "T: cancelled\n"
    saved = read(tmp_path)
    assert saved["state"] == "broken"
    assert saved["reason"] == "cancelled"
    assert saved["env"] == {}


@pytest.mark.parametrize("state", ["queued", "running"])
def test_write_unsettled_job_keeps_env(zone_tool, tmp_path, state):
    zone_tool.write_job(tmp_path, job(state))
    assert read(tmp_path)["env"] == {"JOBENV_FAKE": "x"}
