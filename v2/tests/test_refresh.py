"""Idle refresh: an idle session with a big context gets /refocus, /prepare-for-compact, /compact
and /recover-from-compact while its 1-hour cache is still warm."""
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2 import scheduler  # noqa: E402

NOW = 1_800_000_000.0


def iso(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat().replace("+00:00", "Z")


class Store:
    def __init__(self):
        self.added, self.held = [], {}

    def add(self, channel, sender, kind, recipient, target, body, ride=False):
        self.added.append((target, kind, body))

    def pending(self, k, held=False):
        return self.held.get(k, [])


class RefreshTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.rt = object.__new__(scheduler.Runtime)
        self.rt.team = SimpleNamespace(cfg={})
        self.rt.store = Store()
        self.rt.log = lambda *a: None
        self.paths = {}
        self.rt.transcript = lambda rec: self.paths.get(rec.get("sid"))
        self.sessions = {"Coord-A": SimpleNamespace(key="Coord-A", display="Coord-A")}
        self.st = {"Coord-A": {"sid": "a"}}

    def transcript(self, idle_min, ctx, prompt_min=None):
        p = self.tmp / "a.jsonl"
        last = NOW - idle_min * 60
        recs = []
        if prompt_min is not None:
            recs.append({"type": "user", "timestamp": iso(NOW - prompt_min * 60),
                         "message": {"content": "[codeteam] REQUEST from Orc: x"}})
        recs.append({"type": "assistant", "timestamp": iso(last), "message": {"usage": {
            "input_tokens": 10, "cache_read_input_tokens": ctx - 10, "cache_creation_input_tokens": 0}}})
        recs.append({"type": "system", "subtype": "turn_duration", "timestamp": iso(last)})
        p.write_text("".join(json.dumps(r) + "\n" for r in recs))
        self.paths["a"] = str(p)

    def run_(self, status="idle", pending=None, held=()):
        return self.rt.refresh_idle({"Coord-A": status}, pending or {}, self.st, NOW, set(held), self.sessions)

    def test_idle_big_context_is_refreshed_in_order(self):
        self.transcript(52, 300_000)
        self.assertEqual(self.run_(), ["Coord-A"])
        self.assertEqual([b.split()[0] for _, _, b in self.rt.store.added],
                         ["/refocus", "/prepare-for-compact", "/compact", "/recover-from-compact"])
        self.assertTrue(all(k == scheduler.RUNTIME for _, k, _ in self.rt.store.added))

    def test_not_before_50_minutes(self):
        self.transcript(30, 300_000)
        self.assertEqual(self.run_(), [])

    def test_not_once_the_cache_is_cold(self):
        self.transcript(70, 300_000)
        self.assertEqual(self.run_(), [])

    def test_not_a_small_context(self):
        self.transcript(52, 90_000)
        self.assertEqual(self.run_(), [])

    def test_not_while_working(self):
        self.transcript(52, 300_000)
        self.assertEqual(self.run_(status="working"), [])

    def test_not_with_mail_queued_or_held(self):
        self.transcript(52, 300_000)
        self.assertEqual(self.run_(pending={"Coord-A": [(1, NOW, "NOTE", 0)]}), [])
        self.rt.store.held["Coord-A"] = [{"id": 2}]
        self.assertEqual(self.run_(), [])

    def test_not_when_held_viewed_or_drafted(self):
        self.transcript(52, 300_000)
        self.assertEqual(self.run_(held={"Coord-A"}), [])
        self.st["Coord-A"]["view"] = "subagent"
        self.assertEqual(self.run_(), [])
        self.st["Coord-A"]["view"] = None
        self.st["Coord-A"]["draft_since"] = NOW - 5
        self.assertEqual(self.run_(), [])

    def test_once_per_stretch_of_work(self):
        self.transcript(52, 300_000)
        self.run_()
        n = len(self.rt.store.added)
        self.transcript(52, 300_000, prompt_min=None)
        self.assertEqual(self.run_(), [])                  # no [codeteam] prompt since the refresh
        self.st["Coord-A"]["refreshed_at"] = NOW - 3 * 3600
        self.transcript(52, 300_000, prompt_min=120)       # mail ran after it: a new stretch
        self.assertEqual(self.run_(), ["Coord-A"])
        self.assertEqual(len(self.rt.store.added), 2 * n)

    def test_settings(self):
        self.transcript(52, 300_000)
        self.rt.team.cfg = {"refresh_skip": ["Coord-A"]}
        self.assertEqual(self.run_(), [])
        self.rt.team.cfg = {"refresh_idle_min": 0}
        self.assertEqual(self.run_(), [])
        self.rt.team.cfg = {"refresh_min_tokens": 400_000}
        self.assertEqual(self.run_(), [])


if __name__ == "__main__":
    unittest.main()
