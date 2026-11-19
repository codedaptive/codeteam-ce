"""`sleep` on a working session ends nothing and queues nothing, and says so (the old reply,
"it is ended once idle", read as a pending sleep that would end a coordinator, and its two background leads, between
turns). `sleep` without --force sends /exit with the reason "sleep" (background work is spared) and --force with
"asked", and each prints a line saying which. The team and the runtime are fakes."""
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
        self.status, self.stopped, self.reasons = status, [], []

    def workspace(self):
        return "w"

    def observe(self, ws):
        return {"coord-extract": (self.status,)}

    def stop(self, s, st, reason="asked"):
        self.stopped.append(s.key)
        self.reasons.append(reason)
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

    def test_idle_sleep_uses_sleep_reason(self):
        _, rt, _ = self.sleep("idle")
        self.assertEqual(rt.reasons, ["sleep"])

    def test_force_sleep_uses_asked_reason(self):
        _, rt, _ = self.sleep("working", force=True)
        self.assertEqual(rt.reasons, ["asked"])

    def test_idle_sleep_explains_background_work_and_force(self):
        _, _, out = self.sleep("idle")
        self.assertIn("background work", out)
        self.assertIn("--force", out)


if __name__ == "__main__":
    unittest.main()
