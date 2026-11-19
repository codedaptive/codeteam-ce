"""Plan exit confirmation and discard stale stop state at start."""
import copy
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2.scheduler import Runtime, plan  # noqa: E402

NOW = 1_000_000.0
SESSION = SimpleNamespace(key="a", agent="agent-a", display="Coord-a")


def actions(record):
    return plan(sessions=[("a", "lane")], status={"a": "blocked"}, pending={},
                st={"a": record}, now=NOW, cap=16, swap_idle_min=20,
                blocked_alert_min=2, gather_s=0)


def test_blocked_unconfirmed_exit_after_grace_is_confirmed():
    assert ("confirm_exit", "a") in actions({"stopping_at": NOW - 120, "exit_confirmed": False})


def test_blocked_already_confirmed_exit_is_not_confirmed_again():
    assert ("confirm_exit", "a") not in actions({"stopping_at": NOW - 120, "exit_confirmed": True})


def test_blocked_session_without_exit_is_not_confirmed():
    assert ("confirm_exit", "a") not in actions({"stopping_at": None, "exit_confirmed": False})


class FakeTeam:
    def __init__(self, state):
        self.state = copy.deepcopy(state)

    def state_lock(self):
        return nullcontext()

    def _read_state(self):
        return copy.deepcopy(self.state)

    def _write_state(self, state):
        self.state = copy.deepcopy(state)

    def write_launch_script(self, session, resume_sid, mail):
        return "fake-script", "new-sid"


@pytest.mark.parametrize("field", ["stopping_at", "stop_reason"])
def test_start_clears_previous_stop_state(field):
    st = {"a": {"stopping_at": NOW - 120, "stop_reason": "sleep"}}
    team = FakeTeam(st)
    rt = SimpleNamespace(
        team=team,
        store=SimpleNamespace(pending=lambda key: []),
        herdr=SimpleNamespace(pane_run=lambda pane, command: None),
        ensure_lane_rendered=lambda session: None,
        workspace=lambda: "workspace",
        ensure_pane=lambda session, workspace: "pane",
        panes_by_label=lambda workspace: {"agent-a": {"pane_id": "pane"}},
        log=lambda line: None,
    )
    with patch("codeteam2.scheduler.ts", return_value=NOW):
        assert Runtime.start(rt, SESSION, st)
    assert st["a"].get(field) is None
    assert team.state["a"].get(field) is None
