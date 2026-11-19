import importlib.machinery
import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def zone_tool(monkeypatch):
    name = "zone_tool_team_slot"
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / "bin" / "zone-tool"))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    loader.exec_module(module)
    return module


def test_team_guarantee_is_appended_to_job_line(zone_tool):
    job = {"ticket": "T1", "class": "dev", "state": "done", "team": "team-acme", "session": "s1",
           "worktree": "/x", "cost": 1, "exit": 0, "guarantee": "team"}
    assert zone_tool.job_line(job) == "T1 dev done team-acme s1 /x cost=1 done exit 0 guarantee=team"


def test_job_without_truthy_guarantee_keeps_original_line(zone_tool):
    job = {"ticket": "T1", "class": "dev", "state": "done", "team": "team-acme", "session": "s1",
           "worktree": "/x", "cost": 1, "exit": 0}
    assert zone_tool.job_line(job) == "T1 dev done team-acme s1 /x cost=1 done exit 0"
    job["guarantee"] = ""
    assert zone_tool.job_line(job) == "T1 dev done team-acme s1 /x cost=1 done exit 0"
