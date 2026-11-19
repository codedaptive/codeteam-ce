"""Exit confirmations for voluntary and forced sleep."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2.scheduler import Runtime  # noqa: E402

NOW = 1_000_000.0
SESSION = SimpleNamespace(key="a", agent="agent-a", display="Coord-a")


class FakeHerdr:
    def __init__(self):
        self.keys = []

    def agent_read(self, agent, lines):
        return "Background work is running\nExit and stop tasks"

    def agent_send_keys(self, agent, key):
        self.keys.append(key)


def confirm(reason):
    herdr, logs = FakeHerdr(), []
    rt = SimpleNamespace(herdr=herdr, log=logs.append)
    st = {"a": {"stop_reason": reason, "stopping_at": NOW - 1}}
    with patch("codeteam2.scheduler.ts", return_value=NOW):
        Runtime.confirm_exit(rt, SESSION, st)
    return herdr.keys, st["a"], logs


def test_sleep_cancels_exit_and_holds_background_work():
    keys, rec, logs = confirm("sleep")
    assert keys == ["esc"]
    assert rec["stopping_at"] is None
    assert rec["bg_until"] == NOW + 600
    assert logs == ["exit Coord-a cancelled: background work is running; left alone for 10 min"]


def test_asked_exit_stops_background_work():
    keys, _, logs = confirm("asked")
    assert keys == ["enter"]
    assert logs == ["confirm exit Coord-a: background work stopped"]
