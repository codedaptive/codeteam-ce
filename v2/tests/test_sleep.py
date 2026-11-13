"""`sleep` on a working session ends nothing and queues nothing, and says so (the old reply,
"it is ended once idle", read as a pending sleep that would end a coordinator, and its two background leads, between
turns). The team and the runtime are fakes."""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2 import cli  # noqa: E402

COORD = SimpleNamespace(key="coord-extract", display="Coord-extract")


class FakeTeam:
    def __init__(self):
        self.saved = []

    def session(self, name):
        return COORD if name == "Coord-extract" else None

    def load_state(self):
        return {"coord-extract": {"sid": "s1"}}

    def save_state(self, st):
        self.saved.append(st)


class FakeRuntime:
    def __init__(self, status):
        self.status, self.stopped = status, []

    def workspace(self):
        return "w"

    def observe(self, ws):
        return {"coord-extract": (self.status,)}

    def stop(self, s, st):
        self.stopped.append(s.key)
        return True


class SleepTest(unittest.TestCase):
    def sleep(self, status, force=False):
        team, rt, out = FakeTeam(), FakeRuntime(status), io.StringIO()
        with redirect_stdout(out):
            cli.cmd_sleep(team, rt, SimpleNamespace(name="Coord-extract", force=force))
        return team, rt, out.getvalue()

    def test_a_working_session_is_left_alone_and_nothing_is_queued(self):
        team, rt, out = self.sleep("working")
        self.assertEqual((rt.stopped, team.saved), ([], []))
        self.assertIn("not ended, and nothing is queued", out)
        self.assertNotIn("ended once idle", out)

    def test_an_idle_session_is_ended(self):
        team, rt, out = self.sleep("idle")
        self.assertEqual(rt.stopped, ["coord-extract"])
        self.assertEqual(len(team.saved), 1)

    def test_force_ends_a_working_session(self):
        team, rt, out = self.sleep("working", force=True)
        self.assertEqual(rt.stopped, ["coord-extract"])


if __name__ == "__main__":
    unittest.main()
