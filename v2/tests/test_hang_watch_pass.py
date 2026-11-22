import datetime as dt
import json
import sys
import time
import uuid
from pathlib import Path

import pytest

from conftest import integration_only
from test_v2 import FakeHerdr, FakeStore, FakeTeam, SCREEN_TYPED

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2.hang_watch_pass import hang_watch_pass
from codeteam2.scheduler import Runtime

class RecordingHerdr(FakeHerdr):
    def __init__(self):
        super().__init__({"a": "working"})
        self.actions = []

    def agent_send_keys(self, agent, keys):
        self.actions.append((agent, keys))

    def agent_prompt(self, agent, text, **kwargs):
        self.actions.append((agent, text))
        super().agent_prompt(agent, text, **kwargs)


@pytest.fixture
def setup_watch(tmp_path):
    now = float(int(time.time()))
    sid = str(uuid.uuid4())
    path = tmp_path / f"{sid}.jsonl"
    path.write_text("")
    team = FakeTeam(tmp_path, ["a"])
    herdr = RecordingHerdr()
    store = FakeStore()
    logs = []
    rt = Runtime(team, log=logs.append, herdr=herdr, store=store)
    return rt, {"a": "working"}, {"a": {"sid": sid, "transcript": str(path)}}, now, path, logs


def request(now, wait=301, model="claude-opus-5-5", request_id="req-1"):
    at = dt.datetime.fromtimestamp(now - wait, dt.timezone.utc).isoformat().replace("+00:00", "Z")
    return {"type": "api-request", "id": request_id, "timestamp": at, "params": {"model": model}}


def write_records(path, records):
    path.write_text("".join(json.dumps(record) + "\n" for record in records))


def plant_subagent(path, now, finished=False):
    folder = path.with_suffix("") / "subagents"
    folder.mkdir(parents=True)
    write_records(folder / "agent-child123.jsonl", [request(now, 601, "gpt-6.1-sol(high)", "sub-1")])
    (folder / "agent-child123.meta.json").write_text(json.dumps({"agentType": "test-writer", "finished": finished}))


@integration_only
def test_hung_main_sends_escape_then_continue(setup_watch):
    rt, status, st, now, path, _ = setup_watch
    write_records(path, [request(now)])
    hang_watch_pass(rt, status, st, now)
    assert rt.herdr.actions == [("a", "esc"), ("a", "continue")]


@integration_only
def test_draft_holds_hung_main_without_sending_keys(setup_watch):
    rt, status, st, now, path, _ = setup_watch
    rt.herdr.screen = SCREEN_TYPED
    write_records(path, [request(now)])
    hang_watch_pass(rt, status, st, now)
    assert rt.herdr.actions == []


@integration_only
def test_pending_tool_does_not_trigger_action(setup_watch):
    rt, status, st, now, path, _ = setup_watch
    write_records(path, [request(now), {"type": "assistant", "requestRef": "req-1",
                                      "message": {"content": [{"type": "tool_use", "id": "tool-1", "name": "Bash"}]}}])
    hang_watch_pass(rt, status, st, now)
    assert rt.herdr.actions == []


@integration_only
def test_same_hang_is_acted_on_only_once(setup_watch):
    rt, status, st, now, path, _ = setup_watch
    write_records(path, [request(now)])
    hang_watch_pass(rt, status, st, now)
    hang_watch_pass(rt, status, st, now + 31)
    assert rt.herdr.actions == [("a", "esc"), ("a", "continue")]


@integration_only
def test_hung_subagent_notifies_parent_with_identity_and_model(setup_watch):
    rt, status, st, now, path, _ = setup_watch
    plant_subagent(path, now - 840)
    hang_watch_pass(rt, status, st, now)
    rows = list(rt.store.rows.values())
    assert len(rows) == 1
    assert (rows[0]["kind"], rows[0]["recipient"], rows[0]["target"]) == ("NOTE", "Coord-a", "a")
    assert rows[0]["body"] == ("child123 (test-writer, gpt-6.1-sol(high)) has waited 24 min on a model request: "
                               "TaskStop it and start it again on its own tree")


@integration_only
def test_nested_workflow_agent_noted_once_but_journal_ignored(setup_watch):
    rt, status, st, now, path, _ = setup_watch
    folder = path.with_suffix("") / "subagents" / "workflows" / "wf_x"
    folder.mkdir(parents=True)
    write_records(folder / "agent-nested123.jsonl", [request(now, 1441, "gpt-6.1-sol(high)", "sub-nested")])
    (folder / "agent-nested123.meta.json").write_text(json.dumps({"agentType": "test-writer", "finished": False}))
    write_records(folder / "workflow-journal.jsonl", [request(now, 1441, "gpt-6.1-sol(high)", "journal")])

    hang_watch_pass(rt, status, st, now)
    hang_watch_pass(rt, status, st, now + 31)

    rows = list(rt.store.rows.values())
    assert len(rows) == 1
    assert (rows[0]["kind"], rows[0]["recipient"], rows[0]["target"]) == ("NOTE", "Coord-a", "a")
    assert "nested123" in rows[0]["body"]


@integration_only
def test_bad_session_does_not_stop_hung_session_and_logs_failure(setup_watch):
    rt, status, st, now, path, logs = setup_watch
    rt.team._sessions.extend(FakeTeam(rt.team.dir, ["b"]).sessions())
    rt.herdr.status["b"] = "working"
    status["b"] = "working"
    second = path.parent / f"{uuid.uuid4()}.jsonl"
    st["b"] = {"sid": second.stem, "transcript": str(second)}
    write_records(path, [{"type": "api-request", "id": "broken"}])
    write_records(second, [request(now)])

    error = None
    try:
        hang_watch_pass(rt, status, st, now)
    except KeyError as exc:
        error = exc

    assert rt.herdr.actions == [("b", "esc"), ("b", "continue")]
    assert any("hangwatch" in line for line in logs)
    assert error is None


@integration_only
def test_finished_subagent_is_not_noted(setup_watch):
    rt, status, st, now, path, _ = setup_watch
    plant_subagent(path, now - 840, finished=True)
    hang_watch_pass(rt, status, st, now)
    assert rt.store.rows == {}


@integration_only
def test_action_is_recorded_once_in_jsonl_and_log(setup_watch):
    rt, status, st, now, path, logs = setup_watch
    write_records(path, [request(now)])
    hang_watch_pass(rt, status, st, now)
    lines = (rt.team.dir / "watchdog.jsonl").read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert {key: record[key] for key in ("session", "agent", "model", "wait_s", "action", "request")} == {
        "session": "Coord-a", "agent": None, "model": "claude-opus-5-5", "wait_s": 301,
        "action": "esc+continue", "request": "req-1"}
    assert [line for line in logs if line.startswith("watchdog {")] == ["watchdog " + json.dumps(record, sort_keys=True)]


@integration_only
def test_pass_runs_at_most_once_per_30_seconds(setup_watch):
    rt, status, st, now, path, _ = setup_watch
    write_records(path, [request(now, wait=299)])
    hang_watch_pass(rt, status, st, now)
    hang_watch_pass(rt, status, st, now + 29)
    assert rt.herdr.actions == []
    hang_watch_pass(rt, status, st, now + 30)
    assert rt.herdr.actions == [("a", "esc"), ("a", "continue")]


@integration_only
def test_tick_down_blocks_hung_watchdog(tmp_path, monkeypatch):
    from codeteam2 import scheduler

    now = 1704067500.0
    monkeypatch.setattr(scheduler, "ts", lambda: now)
    sid = str(uuid.uuid4())
    path = tmp_path / f"{sid}.jsonl"
    write_records(path, [request(now)])
    team = FakeTeam(tmp_path, ["a"])
    team.state["a"] = {"sid": sid, "transcript": str(path)}
    (team.dir / "down").write_text("")
    herdr = RecordingHerdr()
    rt = Runtime(team, log=lambda _: None, herdr=herdr, store=FakeStore())
    rt.workspace = lambda create=True: "w1"

    rt.tick()

    assert herdr.actions == []
