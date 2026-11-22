import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import integration_only

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2 import run_watchdogs as watchdogs


@pytest.fixture
def runtime(tmp_path):
    logs = []
    team = SimpleNamespace(dir=tmp_path, halted=lambda: False)
    return SimpleNamespace(team=team, log=logs.append), logs


@integration_only
def test_watchdogs_run_in_order_with_arguments(runtime, monkeypatch):
    rt, _ = runtime
    calls = []
    monkeypatch.setattr(watchdogs, "hang_watch_pass", lambda *args: calls.append(("hang", args)))
    monkeypatch.setattr(watchdogs, "api_recovery_pass", lambda *args: calls.append(("recovery", args)))
    status, st, now = {"a": "working"}, {}, 1704067500.0

    result = watchdogs.run_watchdogs(rt, status, st, now)

    assert result is None
    assert calls == [("hang", (rt, status, st, now)), ("recovery", (rt, status, st, now))]


@integration_only
@pytest.mark.parametrize("blocked", ["down", "halted"])
def test_watchdogs_do_not_run_when_team_stopped(runtime, monkeypatch, blocked):
    rt, _ = runtime
    calls = []
    monkeypatch.setattr(watchdogs, "hang_watch_pass", lambda *args: calls.append("hang"))
    monkeypatch.setattr(watchdogs, "api_recovery_pass", lambda *args: calls.append("recovery"))
    if blocked == "down":
        (rt.team.dir / "down").write_text("")
    else:
        rt.team.halted = lambda: True

    watchdogs.run_watchdogs(rt, {}, {}, 1704067500.0)

    assert calls == []


@integration_only
def test_hang_failure_is_logged_and_recovery_still_runs(runtime, monkeypatch):
    rt, logs = runtime
    calls = []

    def fail(*args):
        raise ValueError("broken hang")

    monkeypatch.setattr(watchdogs, "hang_watch_pass", fail)
    monkeypatch.setattr(watchdogs, "api_recovery_pass", lambda *args: calls.append(args))
    status, st, now = {"a": "working"}, {}, 1704067500.0

    assert watchdogs.run_watchdogs(rt, status, st, now) is None
    assert calls == [(rt, status, st, now)]
    assert any(line.startswith("hangwatch skipped:") for line in logs)


@integration_only
def test_recovery_failure_is_logged_and_returns_normally(runtime, monkeypatch):
    rt, logs = runtime
    calls = []

    def fail(*args):
        raise ValueError("broken recovery")

    monkeypatch.setattr(watchdogs, "hang_watch_pass", lambda *args: calls.append(args))
    monkeypatch.setattr(watchdogs, "api_recovery_pass", fail)
    status, st, now = {"a": "working"}, {}, 1704067500.0

    assert watchdogs.run_watchdogs(rt, status, st, now) is None
    assert calls == [(rt, status, st, now)]
    assert any(line.startswith("api recovery skipped:") for line in logs)
