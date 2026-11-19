"""Idle-lane cleanup and its scheduler wiring, using only temporary trees and queues."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2 import scheduler  # noqa: E402
from codeteam2.clean_idle_lane import clean_idle_lane  # noqa: E402
from conftest import integration_module  # noqa: E402
from test_v2 import FakeHerdr, FakeStore, FakeTeam  # noqa: E402

pytestmark = integration_module


@pytest.fixture
def lane(tmp_path, monkeypatch):
    queue = tmp_path / "queue"
    queue.mkdir()
    monkeypatch.setenv("CODETEAM_QUEUE_DIR", str(queue))
    tree = tmp_path / "workcrews" / "alpha" / "repo-main-alpha"
    tree.mkdir(parents=True)
    (tree / ".git").write_text("gitdir: elsewhere\n")
    v1_team = SimpleNamespace(m={}, repo_name="repo", target="main",
                              lane_dir=lambda name: tmp_path / "workcrews" / name)
    team = SimpleNamespace(t=v1_team, team_json=lambda: {"lanes": {"alpha": {"path": "."}}})
    session = SimpleNamespace(key="alpha", kind="lane", display="Coord-alpha")
    starts, logs = [], []
    monkeypatch.setattr("codeteam2.clean_idle_lane.start_zone_clean",
                        lambda path, home: starts.append((path, home)) or True)
    return SimpleNamespace(team=team, session=session, tree=tree, queue=queue, starts=starts, logs=logs)


def _job(lane, state, worktree):
    (lane.queue / "job.json").write_text(json.dumps({"state": state, "class": "dev", "worktree": str(worktree)}))


def test_idle_git_lane_starts_clean_and_logs_it(lane):
    clean_idle_lane(lane.team, lane.session, lane.logs.append)
    from codeteam2.team import CT_HOME
    assert lane.starts == [(lane.tree, CT_HOME)]
    assert len(lane.logs) == 1
    assert str(lane.tree) in lane.logs[0]


def test_running_job_in_tree_prevents_clean(lane):
    _job(lane, "running", lane.tree)
    clean_idle_lane(lane.team, lane.session, lane.logs.append)
    assert lane.starts == []


def test_running_job_in_nested_tree_prevents_clean(lane):
    _job(lane, "running", lane.tree / ".claude" / "worktrees" / "r1")
    clean_idle_lane(lane.team, lane.session, lane.logs.append)
    assert lane.starts == []


def test_queued_job_does_not_prevent_clean(lane):
    _job(lane, "queued", lane.tree)
    clean_idle_lane(lane.team, lane.session, lane.logs.append)
    assert [path for path, _ in lane.starts] == [lane.tree]


def test_non_git_tree_is_not_cleaned(lane):
    (lane.tree / ".git").unlink()
    clean_idle_lane(lane.team, lane.session, lane.logs.append)
    assert lane.starts == []


def test_zone_folder_lane_is_not_cleaned(lane):
    lane.team.t.m = {"land": {"enabled": True}}
    clean_idle_lane(lane.team, lane.session, lane.logs.append)
    assert lane.starts == []


def test_staff_session_is_not_cleaned(lane):
    lane.session.kind = "staff"
    clean_idle_lane(lane.team, lane.session, lane.logs.append)
    assert lane.starts == []


def test_exception_is_logged_and_does_not_escape(lane):
    def fail():
        raise ValueError("broken team record")

    lane.team.team_json = fail
    clean_idle_lane(lane.team, lane.session, lane.logs.append)
    assert lane.starts == []
    assert any("broken team record" in line for line in lane.logs)


@pytest.fixture
def tick_lane(tmp_path, monkeypatch):
    queue = tmp_path / "queue"
    queue.mkdir()
    monkeypatch.setenv("CODETEAM_QUEUE_DIR", str(queue))
    team = FakeTeam(tmp_path, ["a"])
    herdr = FakeHerdr({})
    runtime = scheduler.Runtime(team, log=lambda *_: None, herdr=herdr, store=FakeStore())
    case = SimpleNamespace(team=team, herdr=herdr, runtime=runtime, cleans=[],
                           actions=[], observation={"a": ("idle", None, 1)}, stopped=True)
    monkeypatch.setattr(scheduler, "plan", lambda *a, **k: case.actions)
    monkeypatch.setattr(scheduler, "clean_idle_lane", lambda t, s, log: case.cleans.append((t, s)))
    monkeypatch.setattr(runtime, "workspace", lambda: "w1")
    monkeypatch.setattr(runtime, "observe", lambda _: case.observation)
    monkeypatch.setattr(runtime, "_waits", lambda: False)

    def stop(s, st, reason):
        if case.stopped:
            st.setdefault(s.key, {})["stop_reason"] = reason
        return case.stopped

    monkeypatch.setattr(runtime, "stop", stop)
    for name in ("ingest_v1_inboxes", "refresh_idle", "patrol", "disk_watch", "backup", "show_in_herdr"):
        monkeypatch.setattr(runtime, name, lambda *a, **k: None)
    return case


def test_idle_stop_cleans_only_once_after_lane_exits(tick_lane):
    c = tick_lane
    c.actions = [("stop", "a", "idle")]
    c.runtime.tick()
    assert c.cleans == []
    assert c.team.state["a"]["clean_on_exit"] is True
    c.actions = []
    c.observation = {"a": ("absent", None, 2)}
    c.runtime.tick()
    assert c.cleans == [(c.team, c.team.sessions()[0])]
    assert c.team.state["a"]["clean_on_exit"] is None
    c.runtime.tick()
    assert c.cleans == [(c.team, c.team.sessions()[0])]


@pytest.mark.parametrize("mail_state", ["queued", "held"])
def test_flagged_absent_lane_with_waiting_mail_is_not_cleaned(tick_lane, mail_state):
    c = tick_lane
    c.team.state["a"] = {"clean_on_exit": True, "status": "absent"}
    c.observation = {"a": ("absent", None, 2)}
    c.runtime.seen.add("a")
    mid = c.runtime.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "new work")
    if mail_state == "held":
        c.runtime.store.mark(mid, "held", "agent_blocked")
    c.runtime.tick()
    assert c.cleans == []
    assert c.team.state["a"]["clean_on_exit"] is None


def test_flagged_absent_unknown_session_clears_mark_without_cleaning(tick_lane):
    c = tick_lane
    c.team.state["missing"] = {"clean_on_exit": True}
    c.runtime.tick()
    assert c.cleans == []
    assert c.team.state["missing"]["clean_on_exit"] is None


def test_cancelled_idle_exit_never_cleans(tick_lane, monkeypatch):
    c = tick_lane
    c.actions = [("stop", "a", "idle")]
    c.runtime.tick()
    assert c.cleans == []
    assert c.team.state["a"]["clean_on_exit"] is True
    keys = []
    monkeypatch.setattr(c.herdr, "agent_read", lambda *a, **k: "Background work is running\nExit and stop tasks", raising=False)
    monkeypatch.setattr(c.herdr, "agent_send_keys", lambda agent, key: keys.append((agent, key)), raising=False)
    c.runtime.confirm_exit(c.team.sessions()[0], c.team.state)
    assert keys == [("a", "esc")]
    assert c.team.state["a"]["clean_on_exit"] is None
    c.actions = []
    c.observation = {"a": ("absent", None, 2)}
    c.runtime.tick()
    assert c.cleans == []


@pytest.mark.parametrize("reason", ["sleep", "idle", "swap"])
def test_background_work_cancellation_clears_cleanup_flag(tick_lane, monkeypatch, reason):
    c = tick_lane
    c.team.state["a"] = {"stop_reason": reason, "clean_on_exit": True}
    keys = []
    monkeypatch.setattr(c.herdr, "agent_read", lambda *a, **k: "Background work is running\nExit and stop tasks", raising=False)
    monkeypatch.setattr(c.herdr, "agent_send_keys", lambda agent, key: keys.append(key), raising=False)
    c.runtime.confirm_exit(c.team.sessions()[0], c.team.state)
    assert keys == ["esc"]
    assert c.team.state["a"]["clean_on_exit"] is None


@pytest.mark.parametrize("reason", ["swap", "asked", "sleep"])
def test_non_idle_stop_never_cleans_after_exit(tick_lane, reason):
    c = tick_lane
    c.actions = [("stop", "a", reason)]
    c.runtime.tick()
    assert not c.team.state["a"].get("clean_on_exit")
    c.actions = []
    c.observation = {"a": ("absent", None, 2)}
    c.runtime.tick()
    assert c.cleans == []


def test_refused_idle_stop_does_not_flag_lane(tick_lane):
    c = tick_lane
    c.stopped = False
    c.actions = [("stop", "a", "idle")]
    c.runtime.tick()
    assert not c.team.state["a"].get("clean_on_exit")
    assert c.cleans == []


def test_staff_idle_stop_does_not_flag_or_clean(tick_lane):
    c = tick_lane
    c.team.sessions()[0].kind = "staff"
    c.actions = [("stop", "a", "idle")]
    c.runtime.tick()
    assert not c.team.state["a"].get("clean_on_exit")
    assert c.cleans == []


def test_flagged_lane_missing_from_observation_is_cleaned_before_plan(tick_lane, monkeypatch):
    c = tick_lane
    c.team.state["a"] = {"clean_on_exit": True}
    c.observation = {}
    seen = []
    monkeypatch.setattr(scheduler, "plan", lambda *a, **k: seen.append((list(c.cleans), c.team.state["a"]["clean_on_exit"])) or [])
    c.runtime.tick()
    assert seen == [([(c.team, c.team.sessions()[0])], None)]
