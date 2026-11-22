import json
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conftest import integration_module
from codeteam2.scheduler import Runtime
from test_v2 import FakeHerdr, FakeStore, FakeTeam, SCREEN_TYPED

pytestmark = integration_module

def error(ident="error-1", timestamp="2024-01-01T00:00:00Z"):
    return {"type": "assistant", "timestamp": timestamp, "uuid": ident,
            "isApiErrorMessage": True, "error": "overloaded",
            "message": {"model": "<synthetic>", "content": []}}


def plant(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    os.utime(path, (1704067400, 1704067400))


def success(root, timestamp="2024-01-01T00:00:10Z"):
    plant(root / "other-project" / f"{uuid.uuid4()}.jsonl", [
        {"type": "assistant", "timestamp": timestamp,
         "message": {"model": "claude-opus-5-5", "content": []}}])


@pytest.fixture
def recovery(tmp_path):
    from codeteam2.api_recovery_pass import api_recovery_pass
    team_dir = tmp_path / "team"
    team_dir.mkdir()
    root = tmp_path / "projects"
    sid = str(uuid.uuid4())
    transcript = root / "project" / f"{sid}.jsonl"
    plant(transcript, [error()])
    team = FakeTeam(team_dir, ["a"])
    herdr = FakeHerdr({"a": "idle"})
    logs = []
    rt = Runtime(team, log=logs.append, herdr=herdr, store=FakeStore())
    state = {"a": {"sid": sid, "transcript": str(transcript)}}
    return api_recovery_pass, rt, herdr, state, root, transcript, logs


def test_success_elsewhere_sends_continue_and_records_watchdog(recovery):
    run, rt, herdr, state, root, _, logs = recovery
    success(root)
    run(rt, {"a": "idle"}, state, 1704067300, root=root)
    assert herdr.prompts == [("a", "continue")]
    lines = (rt.team.dir / "watchdog.jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["action"] == "continue after api error"
    assert len([line for line in logs if line.startswith("watchdog {")]) == 1
    assert json.loads(next(line[len("watchdog "):] for line in logs if line.startswith("watchdog {"))) == json.loads(lines[0])


def test_no_success_does_not_send(recovery):
    run, rt, herdr, state, root, _, _ = recovery
    run(rt, {"a": "idle"}, state, 1704067300, root=root)
    assert herdr.prompts == []


def test_success_before_error_does_not_send(recovery):
    run, rt, herdr, state, root, _, _ = recovery
    success(root, "2023-12-31T23:59:59Z")
    run(rt, {"a": "idle"}, state, 1704067300, root=root)
    assert herdr.prompts == []


def test_working_session_does_not_send(recovery):
    run, rt, herdr, state, root, _, _ = recovery
    success(root)
    run(rt, {"a": "working"}, state, 1704067300, root=root)
    assert herdr.prompts == []


def test_draft_prevents_send(recovery):
    run, rt, herdr, state, root, _, _ = recovery
    herdr.screen = SCREEN_TYPED
    success(root)
    run(rt, {"a": "idle"}, state, 1704067300, root=root)
    assert herdr.prompts == []


def test_done_session_can_be_nudged(recovery):
    run, rt, herdr, state, root, _, _ = recovery
    success(root)
    run(rt, {"a": "done"}, state, 1704067300, root=root)
    assert herdr.prompts == [("a", "continue")]


def test_one_nudge_per_error_record(recovery):
    run, rt, herdr, state, root, _, _ = recovery
    success(root)
    run(rt, {"a": "idle"}, state, 1704067300, root=root)
    run(rt, {"a": "idle"}, state, 1704067331, root=root)
    assert herdr.prompts == [("a", "continue")]


def test_new_error_record_can_be_nudged_again(recovery):
    run, rt, herdr, state, root, transcript, _ = recovery
    success(root)
    run(rt, {"a": "idle"}, state, 1704067300, root=root)
    plant(transcript, [error("error-2", "2024-01-01T00:00:20Z")])
    success(root, "2024-01-01T00:00:30Z")
    run(rt, {"a": "idle"}, state, 1704067331, root=root)
    assert herdr.prompts == [("a", "continue"), ("a", "continue")]


def test_tick_notifies_on_working_to_idle_api_error(tmp_path):
    team = FakeTeam(tmp_path, ["a"])
    herdr = FakeHerdr({"a": "working"})
    rt = Runtime(team, log=lambda _: None, herdr=herdr, store=FakeStore())
    rt.workspace = lambda create=True: "w1"
    rt.tick()
    herdr.status["a"] = "idle"
    herdr.screen = "⏺ done\n  ⎿  API Error: 529 Overloaded\n"
    rt.tick()
    assert len(herdr.notified) == 1
    assert "API Error: 529 Overloaded" in herdr.notified[0][1]


def test_tick_down_blocks_api_recovery(tmp_path, monkeypatch):
    from codeteam2 import scheduler

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(scheduler, "ts", lambda: 1704067500.0)
    root = tmp_path / ".claude" / "projects"
    sid = str(uuid.uuid4())
    transcript = root / "project" / f"{sid}.jsonl"
    plant(transcript, [error()])
    success(root)
    team_dir = tmp_path / "team"
    team_dir.mkdir()
    team = FakeTeam(team_dir, ["a"])
    team.state["a"] = {"sid": sid, "transcript": str(transcript)}
    (team_dir / "down").write_text("")
    herdr = FakeHerdr({"a": "idle"})
    rt = Runtime(team, log=lambda _: None, herdr=herdr, store=FakeStore())
    rt.workspace = lambda create=True: "w1"

    rt.tick()

    assert herdr.prompts == []
