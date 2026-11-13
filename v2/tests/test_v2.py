"""codeteam v2 unit tests: the loop's rules (plan), the loop itself against a fake herdr, and the
message store. No herdr needed."""
import contextlib
import datetime as dt
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import integration_only  # noqa: E402
from codeteam2.scheduler import BUNDLE_MAX, Runtime, bundle, plan  # noqa: E402
from codeteam2.store import RUNTIME, Store  # noqa: E402
from codeteam2.team import Team  # noqa: E402
from codeteam2.transport import Refused  # noqa: E402

NOW = 1_000_000.0
S = [("orc", "staff"), ("a", "lane"), ("b", "lane")]


def P(**kw):
    # gather_s=0 unless a test is about gathering: these tests are about the other rules.
    base = dict(sessions=S, status={}, pending={}, st={}, now=NOW, cap=16, swap_idle_min=20, blocked_alert_min=2,
                gather_s=0)
    base.update(kw)
    return plan(**base)


def delivered(acts, key):
    return [a[2] for a in acts if a[0] == "deliver" and a[1] == key]


def stops(acts, key):
    # plan's stop actions carry a reason, ("stop", key, reason): match any reason, so a stop for
    # any cause fails the check.
    return [x for x in acts if x[0] == "stop" and x[1] == key]


class PlanTests(unittest.TestCase):
    def test_deliver_only_when_ready(self):
        pend = {"a": [(1, NOW - 5)]}
        for s, want in (("idle", True), ("done", True), ("working", False), ("blocked", False), ("unknown", False)):
            acts = P(status={"orc": "idle", "a": s, "b": "absent"}, pending=pend)
            self.assertEqual(("deliver", "a", (1,)) in acts, want, s)

    def test_everything_waiting_goes_in_one_prompt(self):
        pend = {"a": [(1, NOW - 9), (2, NOW - 5)]}
        self.assertEqual(delivered(P(status={"a": "idle"}, pending=pend), "a"), [(1, 2)])
        # just delivered, turn not seen yet: wait
        acts = P(status={"a": "idle"}, pending={"a": [(3, NOW - 5)]},
                 st={"a": {"awaiting_turn": True, "delivered_at": NOW - 3}})
        self.assertFalse(delivered(acts, "a"))
        # the grace passed with no turn seen and nothing to put back: deliver
        acts = P(status={"a": "idle"}, pending={"a": [(3, NOW - 5)]},
                 st={"a": {"awaiting_turn": True, "delivered_at": NOW - 60}})
        self.assertEqual(delivered(acts, "a"), [(3,)])

    def test_gather_window_is_bounded(self):
        cold = {"a": {"state_since": NOW - 600}}         # idle 10 min: its prompt cache is cold
        # The oldest message is 10 s old: wait for company.
        self.assertFalse(delivered(P(status={"a": "idle"}, pending={"a": [(1, NOW - 10)]}, st=cold, gather_s=30), "a"))
        # It has waited 31 s: go, with everything that joined since (even a message 1 s old).
        acts = P(status={"a": "idle"}, pending={"a": [(1, NOW - 31), (2, NOW - 1)]}, st=cold, gather_s=30)
        self.assertEqual(delivered(acts, "a"), [(1, 2)])

    def test_warm_session_is_prompted_at_once(self):
        # Its turn ended 20 s ago: a wake is cheap, so no waiting for company.
        warm = {"a": {"state_since": NOW - 20}}
        acts = P(status={"a": "idle"}, pending={"a": [(1, NOW - 1)]}, st=warm, gather_s=30, warm_s=240)
        self.assertEqual(delivered(acts, "a"), [(1,)])

    def test_runtime_commands_go_alone_and_in_order(self):
        # A runtime command at the head goes at once, alone, even inside the gather window.
        pend = {"a": [(1, NOW - 1, RUNTIME), (2, NOW - 1, "NOTE")]}
        cold = {"a": {"state_since": NOW - 600}}
        self.assertEqual(delivered(P(status={"a": "idle"}, pending=pend, st=cold, gather_s=30), "a"), [(1,)])
        # Messages ahead of a runtime command go first, and the bundle stops at it.
        pend = {"a": [(1, NOW - 40, "NOTE"), (2, NOW - 40, RUNTIME), (3, NOW - 40, "NOTE")]}
        self.assertEqual(delivered(P(status={"a": "idle"}, pending=pend, gather_s=30), "a"), [(1,)])

    def test_bundle_size_cap(self):
        items = [(i, NOW - 60) for i in range(1, BUNDLE_MAX + 3)]
        self.assertEqual(bundle(items, NOW, 30), tuple(range(1, BUNDLE_MAX + 1)))

    def test_no_delivery_before_first_turn(self):
        pend = {"a": [(1, NOW - 5)]}
        st = {"a": {"starting_at": NOW - 10, "first_turn_seen": False}}
        self.assertFalse(delivered(P(status={"a": "idle"}, pending=pend, st=st), "a"))
        st["a"]["first_turn_seen"] = True
        self.assertEqual(delivered(P(status={"a": "idle"}, pending=pend, st=st), "a"), [(1,)])
        st = {"a": {"starting_at": NOW - 500, "first_turn_seen": False}}     # grace over
        self.assertEqual(delivered(P(status={"a": "idle"}, pending=pend, st=st), "a"), [(1,)])
        # ready and quiet for a while, well after the start: the turn ran even if no one saw it
        st = {"a": {"starting_at": NOW - 40, "first_turn_seen": False, "state_since": NOW - 20}}
        self.assertEqual(delivered(P(status={"a": "idle"}, pending=pend, st=st), "a"), [(1,)])
        # idle for a moment just after the start: not yet
        st = {"a": {"starting_at": NOW - 8, "first_turn_seen": False, "state_since": NOW - 3}}
        self.assertFalse(delivered(P(status={"a": "idle"}, pending=pend, st=st), "a"))

    def test_redeliver_when_no_turn(self):
        st = {"a": {"awaiting_turn": True, "delivered_at": NOW - 60, "last_mids": [7, 8]}}
        self.assertIn(("redeliver", "a", (7, 8)), P(status={"a": "idle"}, st=st))
        st = {"a": {"awaiting_turn": True, "delivered_at": NOW - 5, "last_mids": [7, 8]}}
        self.assertFalse([x for x in P(status={"a": "idle"}, st=st) if x[0] == "redeliver"])
        # a state file written before bundles (last_mid) still works
        st = {"a": {"awaiting_turn": True, "delivered_at": NOW - 60, "last_mid": 7}}
        self.assertIn(("redeliver", "a", (7,)), P(status={"a": "idle"}, st=st))

    def test_wake_lane_with_mail_up_to_cap(self):
        pend = {"a": [(1, NOW - 50)], "b": [(2, NOW - 10)]}
        acts = P(status={"orc": "idle", "a": "absent", "b": "absent"}, pending=pend, cap=1)
        self.assertIn(("start", "a"), acts)          # oldest mail first
        self.assertNotIn(("start", "b"), acts)

    def test_no_double_start(self):
        acts = P(status={"a": "absent"}, pending={"a": [(1, NOW)]}, st={"a": {"starting_at": NOW - 10}})
        self.assertNotIn(("start", "a"), acts)

    def test_swap_idle_lane_at_cap(self):
        pend = {"b": [(2, NOW - 10)]}
        st = {"a": {"state_since": NOW - 25 * 60}}
        acts = P(status={"a": "idle", "b": "absent"}, pending=pend, st=st, cap=1)
        self.assertIn(("stop", "a", "swap"), acts)
        self.assertNotIn(("start", "b"), acts)
        # not idle long enough: no swap
        acts = P(status={"a": "idle", "b": "absent"}, pending=pend, st={"a": {"state_since": NOW - 60}}, cap=1)
        self.assertFalse(stops(acts, "a"))
        # never swap a lane that is working
        acts = P(status={"a": "working", "b": "absent"}, pending=pend, st=st, cap=1)
        self.assertFalse(stops(acts, "a"))

    def test_over_cap_idle_lanes_go(self):
        st = {"a": {"state_since": NOW - 300}, "b": {"state_since": NOW - 600}}
        acts = P(status={"a": "done", "b": "idle"}, st=st, cap=1, swap_idle_min=1)
        self.assertEqual([x for x in acts if x[0] == "stop"], [("stop", "b", "swap")])   # idle longest goes
        acts = P(status={"a": "working", "b": "working"}, st=st, cap=1, swap_idle_min=1)
        self.assertFalse([x for x in acts if x[0] == "stop"])                   # never a working lane

    def test_swap_passes_over_a_lane_held_in_a_subagent_view(self):
        """A lane whose pane shows a subagent's view cannot take /exit: swap and over-cap pick another lane, idle exit skips it."""
        sessions = S + [("c", "lane")]
        view = {"view": "request-lead", "view_since": NOW - 40 * 60}
        st = {"a": {"state_since": NOW - 40 * 60, **view}, "b": {"state_since": NOW - 25 * 60}}
        acts = P(sessions=sessions, status={"a": "idle", "b": "idle", "c": "absent"},
                 pending={"c": [(3, NOW - 10)]}, st=st, cap=2)
        self.assertIn(("stop", "b", "swap"), acts)
        self.assertFalse([x for x in acts if x[0] == "stop" and x[1] == "a"])
        # over the cap: a idled longest but is held in a view, so b goes
        acts = P(status={"a": "idle", "b": "idle"}, st=st, cap=1, swap_idle_min=1)
        self.assertEqual([x for x in acts if x[0] == "stop"], [("stop", "b", "swap")])
        # idle exit: not while held in a view; the same lane in its main view is ended
        long_idle = {"a": {"state_since": NOW - 7 * 3600, **view}}
        acts = P(status={"a": "idle"}, st=long_idle, idle_exit_min=360)
        self.assertFalse(stops(acts, "a"))
        acts = P(status={"a": "idle"}, st={"a": {"state_since": NOW - 7 * 3600}}, idle_exit_min=360)
        self.assertIn(("stop", "a", "idle"), acts)

    def test_swap_passes_over_a_lane_with_a_draft(self):
        """A lane with unsent text in its input box cannot take /exit either: swap, over-cap and idle exit pass over it."""
        sessions = S + [("c", "lane")]
        draft = {"draft_since": NOW - 40 * 60}
        st = {"a": {"state_since": NOW - 40 * 60, **draft}, "b": {"state_since": NOW - 25 * 60}}
        acts = P(sessions=sessions, status={"a": "idle", "b": "idle", "c": "absent"},
                 pending={"c": [(3, NOW - 10)]}, st=st, cap=2)
        self.assertIn(("stop", "b", "swap"), acts)
        self.assertFalse([x for x in acts if x[0] == "stop" and x[1] == "a"])
        # over the cap: a idled longest but holds a draft, so b goes
        acts = P(status={"a": "idle", "b": "idle"}, st=st, cap=1, swap_idle_min=1)
        self.assertEqual([x for x in acts if x[0] == "stop"], [("stop", "b", "swap")])
        # idle exit: not while a draft is in its input box
        long_idle = {"a": {"state_since": NOW - 7 * 3600, **draft}}
        acts = P(status={"a": "idle"}, st=long_idle, idle_exit_min=360)
        self.assertFalse(stops(acts, "a"))

    def test_swap_and_over_cap_pass_over_a_lane_on_hold(self):
        """A lane the user put on hold stays as it is: the cap swap and the over-cap pass take another idle lane,
        and when the only idle lane is on hold, nothing is stopped."""
        sessions = S + [("c", "lane")]
        st = {"a": {"state_since": NOW - 40 * 60}, "b": {"state_since": NOW - 25 * 60}}
        # cap swap: a idled longest but is on hold, so b makes room for c
        acts = P(sessions=sessions, status={"a": "idle", "b": "idle", "c": "absent"},
                 pending={"c": [(3, NOW - 10)]}, st=st, cap=2, held={"a"})
        self.assertIn(("stop", "b", "swap"), acts)
        self.assertFalse([x for x in acts if x[0] == "stop" and x[1] == "a"])
        # over the cap: a idled longest but is on hold, so b goes
        acts = P(status={"a": "idle", "b": "idle"}, st=st, cap=1, swap_idle_min=1, held={"a"})
        self.assertEqual([x for x in acts if x[0] == "stop"], [("stop", "b", "swap")])
        # the only idle lane is on hold: no swap, b waits for a slot
        acts = P(status={"a": "idle", "b": "absent"}, pending={"b": [(2, NOW - 10)]},
                 st={"a": {"state_since": NOW - 40 * 60}}, cap=1, held={"a"})
        self.assertFalse([x for x in acts if x[0] == "stop"])
        self.assertNotIn(("start", "b"), acts)              # a on hold still holds its slot against the cap

    def test_leaving_lane(self):
        st = {"a": {"state_since": NOW - 600, "stopping_at": NOW - 10},
              "b": {"state_since": NOW - 600}}
        # a is leaving: it does not count against the cap, so b is not stopped as well
        acts = P(status={"a": "blocked", "b": "idle"}, st=st, cap=1, swap_idle_min=1)
        self.assertFalse(stops(acts, "b"))
        self.assertIn(("confirm_exit", "a"), acts)
        self.assertFalse([x for x in acts if x[0] == "alert"])
        st["a"]["exit_confirmed"] = True
        self.assertNotIn(("confirm_exit", "a"), P(status={"a": "blocked", "b": "idle"}, st=st, cap=1))

    def test_launch_request_wakes_within_cap(self):
        acts = P(status={"a": "absent", "b": "absent"}, st={"b": {"wake_requested": NOW - 5}}, cap=1)
        self.assertIn(("start", "b"), acts)
        acts = P(status={"a": "working", "b": "absent"}, st={"b": {"wake_requested": NOW - 5}}, cap=1)
        self.assertNotIn(("start", "b"), acts)

    def test_staff_start_without_cap(self):
        acts = P(status={"orc": "absent", "a": "idle", "b": "idle"}, pending={"orc": [(5, NOW)]}, cap=0)
        self.assertIn(("start", "orc"), acts)

    def test_held_session_is_never_started_or_prompted(self):
        acts = P(status={"orc": "absent"}, pending={"orc": [(1, NOW - 60)]}, held={"orc"})
        self.assertNotIn(("start", "orc"), acts)
        acts = P(status={"orc": "idle"}, pending={"orc": [(1, NOW - 60)]}, held={"orc"})
        self.assertFalse(delivered(acts, "orc"))
        acts = P(status={"a": "absent"}, st={"a": {"wake_requested": NOW - 5}}, held={"a"})
        self.assertNotIn(("start", "a"), acts)

    def test_blocked_alert_once(self):
        acts = P(status={"a": "blocked"}, st={"a": {"state_since": NOW - 300}})
        self.assertIn(("alert", "a", 5.0), acts)
        acts = P(status={"a": "blocked"}, st={"a": {"state_since": NOW - 300, "alerted": True}})
        self.assertFalse([x for x in acts if x[0] == "alert"])
        acts = P(status={"a": "blocked"}, st={"a": {"state_since": NOW - 30}})
        self.assertFalse([x for x in acts if x[0] == "alert"])


# ---------------------------------------------------------------------- the loop, against fakes
class FakeHerdr:
    """Just enough of herdr for Runtime.tick: one workspace, labelled panes, agents with a status."""

    def __init__(self, agents):
        self.status = dict(agents)          # agent name -> status
        self.prompts = []                   # (agent, text)
        self.refuse = None
        self.runs = []                      # (pane, command) typed by pane_run
        self.notified = []                  # (title, body) of every notify to the owner
        self.seqs = {}                      # agent name -> its state_change_seq (default 1)
        self.list_calls = 0
        self.get_calls = []
        self.pane_calls = []

    def workspaces(self):
        return [{"workspace_id": "w1", "label": "fake"}]

    def panes(self, ws=None):
        self.pane_calls.append(ws)
        return [{"pane_id": f"p-{n}", "label": n, "tab_id": "t1"} for n in self.status]

    completions = {}

    def _agent_rows(self):
        return [{"pane_id": f"p-{n}", "workspace_id": "w1", "name": n, "agent_status": s,
                 "state_change_seq": self.seqs.get(n, 1),
                 "completion_seq": self.completions.get(n), "terminal_id": f"t-{n}"}
                for n, s in self.status.items() if s != "absent"]

    def agents(self):
        self.list_calls += 1
        return self._agent_rows()

    def agent_get(self, target):
        from codeteam2.herdr import HerdrError
        self.get_calls.append(target)
        for row in self._agent_rows():
            if row["pane_id"] == target:
                return row
        raise HerdrError("agent_not_found")

    def agent_prompt(self, target, text, **_):
        from codeteam2.herdr import HerdrError
        if self.refuse:
            raise HerdrError(self.refuse)
        self.prompts.append((target, text))

    def pane_metadata(self, *a, **k):
        # Every sidebar update, as (args, kwargs): tests read the tokens sent for a pane.
        if self.metadata is None:
            self.metadata = []
        self.metadata.append((a, k))
        return {}

    metadata = None

    def notify(self, *a, **k):
        self.notified.append(a)

    def agent_rename(self, *a):
        return {}

    screen = None                           # what agent_screen shows (None: nothing readable)

    def agent_screen(self, target, lines=40):
        return self.screen

    def pane_run(self, pane, command):
        self.runs.append((pane, command))

    def pane_rename(self, *a):
        return {}

    closed = None

    def pane_close(self, pane):
        (self.closed if self.closed is not None else setattr(self, "closed", []) or self.closed).append(pane)
        return {}


class FakeStore:
    """The message store's calls that tick and deliver make, over rows in a dict (store.Store's semantics,
    no SQLite). Rows come back as copies, as the real store's fetched rows are snapshots."""

    TS = "2026-11-09T12:00:00+00:00"

    def __init__(self):
        self.rows = {}

    def add(self, channel, sender, kind, recipient, target, body, ride=False):
        mid = len(self.rows) + 1
        self.rows[mid] = {"id": mid, "ts": self.TS, "channel": channel, "sender": sender, "kind": kind.upper(),
                          "recipient": recipient, "target": target, "body": body, "ride": 1 if ride else 0,
                          "state": "queued", "attempts": 0, "flags": 0, "note": None, "delivered_at": None}
        return mid

    def get(self, mid):
        row = self.rows.get(mid)
        return dict(row) if row else None

    def pending(self, target=None, held=False):
        states = ("queued", "held") if held else ("queued",)
        return [dict(r) for _, r in sorted(self.rows.items())
                if r["state"] in states and (not target or r["target"] == target)]

    def mark(self, mid, state, note=None, flags=0, only_from=None):
        row = self.rows.get(mid)
        if row is None or (only_from is not None and row["state"] != only_from):
            return False
        if state != "queued":
            row["attempts"] += 1
        if state == "delivered":
            row["delivered_at"] = self.TS
        row.update(state=state, note=note, flags=row["flags"] | flags)
        return True

    def settle_held(self, target, mids, note):
        settled = [m for m in sorted(mids) if m in self.rows
                   and self.rows[m]["target"] == target and self.rows[m]["state"] == "held"]
        for m in settled:
            self.rows[m].update(state="delivered", delivered_at=self.TS, note=note)
        return settled

    def release(self, target, note):
        back = [m for m, r in sorted(self.rows.items()) if r["target"] == target and r["state"] == "held"]
        for m in back:
            self.rows[m].update(state="queued", note=note)
        return back


class FakePath:
    """A team directory with nothing in it: every path under it is itself, absent, and writes go nowhere."""

    def __truediv__(self, _name):
        return self

    def exists(self):
        return False

    def is_dir(self):
        return False

    def write_text(self, _text):
        return None

    def replace(self, _target):
        return None


class FakeTeam:
    def __init__(self, d, keys):
        self.dir = Path(d)
        self.product = "fake"
        self.herdr_session = "test"
        self.cfg = {}
        self.cap, self.swap_idle_min, self.blocked_alert_min, self.poll_s, self.gather_s = 16, 20, 2, 2, 0
        self.disk_check_s = 0       # the loop's disk check reads the real volume; test_disk_watch covers it
        self.t = SimpleNamespace(manifest="/m.toml", inbox=lambda k: self.dir / "no-inbox" / k,
                                 orc_name=lambda: "Orc-Fake", root=self.dir)
        self._sessions = [SimpleNamespace(key=k, display=f"Coord-{k}", kind="lane", agent=k, cwd=self.dir)
                          for k in keys]
        self.state = {}

    def sessions(self):
        return self._sessions

    def load_state(self):
        return self.state

    def _read_state(self):
        return self.state

    def save_state(self, st):
        self.state = st

    def state_lock(self):
        return contextlib.nullcontext()

    def _write_state(self, st):
        self.state = st

    def update_state(self, key, fields):
        self.state.setdefault(key, {}).update(fields)

    def session(self, name):
        return next((s for s in self._sessions if name in (s.key, s.display, s.agent)), None)

    def held(self, key):
        return False

    launched = None

    def write_launch_script(self, s, resume_sid=None, mail=None):
        self.launched = (s.key, mail)
        return self.dir / "launch.sh", "sid-1"


class DiskTeam(Team, FakeTeam):
    """Real state-file operations, with session and launch setup kept in memory."""

    __init__ = FakeTeam.__init__
    sessions = FakeTeam.sessions
    session = FakeTeam.session
    held = FakeTeam.held
    write_launch_script = FakeTeam.write_launch_script
    cap = 16

    def keep_awake(self):
        return set()


class ObservationFreshnessTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        from itertools import count
        from codeteam2 import scheduler
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.team = DiskTeam(self.d.name, ["a", "b"])
        self.team.halted = lambda: False
        self.herdr = FakeHerdr({"a": "idle", "b": "idle", "other-team": "working"})
        self.store = Store(Path(self.d.name) / "m.db")
        self.addCleanup(self.store.db.close)
        self.rt = Runtime(self.team, log=lambda *_: None, herdr=self.herdr, store=self.store)
        self.rt.workspace = lambda create=True: "w1"
        clock = count(2000000000)
        self.now = lambda: float(next(clock))
        self.clock_patch = patch.object(scheduler, "ts", self.now)
        self.clock_patch.start()
        self.addCleanup(self.clock_patch.stop)
        self.monotonic_patch = patch.object(scheduler.time, "monotonic", self.now)
        self.monotonic_patch.start()
        self.addCleanup(self.monotonic_patch.stop)

    def test_observe_only_gets_own_labelled_agents(self):
        panes = self.herdr.panes
        def measured_panes(ws):
            return [dict(p, workspace_id=ws, terminal_id="term_x", agent="claude", agent_status="idle")
                    for p in panes(ws)]
        self.herdr.panes = measured_panes
        result = self.rt.observe("w1")
        self.assertEqual(self.herdr.list_calls, 0)
        self.assertEqual(self.herdr.pane_calls, ["w1"])
        self.assertEqual(self.herdr.get_calls, ["p-a", "p-b"])
        self.assertEqual(result["a"], ("idle", "p-a", 1, None, "t-a"))

    def test_observe_skips_measured_bare_pane(self):
        self.herdr.panes = lambda ws: [
            {"workspace_id": "w1", "pane_id": "p-a", "tab_id": "w1:t1", "terminal_id": "term_x",
             "label": "a", "agent_status": "unknown"}]
        self.herdr.status["a"] = "absent"
        result = self.rt.observe("w1")
        self.assertEqual(self.herdr.list_calls, 0)
        self.assertEqual(self.herdr.get_calls, [])
        self.assertEqual(result["a"], ("absent", "p-a", None))

    def test_observe_gets_legacy_pane_without_agent_keys(self):
        result = self.rt.observe("w1")
        self.assertIn("p-a", self.herdr.get_calls)
        self.assertEqual(result["a"], ("idle", "p-a", 1, None, "t-a"))

    def test_observe_agent_not_found_is_absent(self):
        self.herdr.status["a"] = "absent"
        result = self.rt.observe("w1")
        self.assertIn("p-a", self.herdr.get_calls)
        self.assertEqual(result["a"], ("absent", "p-a", None))

    def test_observe_other_agent_error_propagates(self):
        from codeteam2.herdr import HerdrError
        def fail(target):
            raise HerdrError("server_error")
        self.herdr.agent_get = fail
        with self.assertRaises(HerdrError) as raised:
            self.rt.observe("w1")
        self.assertEqual(raised.exception.code, "server_error")

    def test_observe_renames_one_then_rereads_and_next_call_renames_second(self):
        names = {"p-a": "old-a", "p-b": "old-b"}
        renames = []
        rows = self.herdr._agent_rows
        self.herdr._agent_rows = lambda: [dict(row, name=names.get(row["pane_id"], row["name"])) for row in rows()]
        original_get = self.herdr.agent_get
        def get(target):
            return dict(original_get(target), name=names[target], state_change_seq=len(renames) + 1)
        def rename(target, name):
            renames.append((target, name))
            names[target] = name
        self.herdr.agent_get = get
        self.herdr.agent_rename = rename
        result = self.rt.observe("w1")
        self.assertEqual(renames, [("p-a", "a")])
        self.assertEqual(self.herdr.pane_calls, ["w1", "w1"])
        self.assertEqual(self.herdr.get_calls, ["p-a", "p-b", "p-a", "p-b"])
        self.assertEqual(result["a"][2], 2)
        self.rt.observe("w1")
        self.assertEqual(renames, [("p-a", "a"), ("p-b", "b")])

    def test_observe_rereads_after_failed_rename(self):
        from codeteam2.herdr import HerdrError
        original_get = self.herdr.agent_get
        self.herdr.agent_get = lambda target: dict(original_get(target), name="wrong")
        def fail(target, name):
            raise HerdrError("rename_failed")
        self.herdr.agent_rename = fail
        self.rt.observe("w1")
        self.assertEqual(self.herdr.pane_calls, ["w1", "w1"])
        self.assertEqual(self.herdr.get_calls, ["p-a", "p-b", "p-a", "p-b"])

    def test_obs_at_precedes_final_read_after_rename(self):
        reads = []
        panes = self.herdr.panes
        def read(ws):
            reads.append(self.now())
            return panes(ws)
        self.herdr.panes = read
        original_get = self.herdr.agent_get
        self.herdr.agent_get = lambda target: dict(original_get(target), name="wrong")
        self.rt.observe("w1")
        self.assertEqual(len(reads), 2)
        self.assertLess(reads[0], self.rt.obs_at)
        self.assertLess(self.rt.obs_at, reads[1])

    def track_actions(self):
        self.herdr.last_action = 0.0
        for name in ("agent_prompt", "pane_run", "pane_close", "pane_rename", "agent_rename"):
            original = getattr(self.herdr, name)
            def action(*args, _original=original, **kwargs):
                result = _original(*args, **kwargs)
                self.herdr.last_action = self.now()
                return result
            setattr(self.herdr, name, action)

    def test_tick_delivers_one_then_other_on_next_observation(self):
        from unittest.mock import patch
        self.track_actions()
        a = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "first")
        b = self.store.add("general", "Orc", "REQUEST", "Coord-b", "b", "second")
        with patch("codeteam2.scheduler.plan", side_effect=[[("deliver", "a", (a,)), ("deliver", "b", (b,))],
                                                            [("deliver", "b", (b,))]]):
            self.rt.tick()
            self.assertEqual([p[0] for p in self.herdr.prompts], ["a"])
            self.rt.tick()
        self.assertEqual([p[0] for p in self.herdr.prompts], ["a", "b"])

    def test_tick_defers_second_delivery_when_wall_clock_steps_backward(self):
        from unittest.mock import patch
        from codeteam2 import herdr, scheduler

        wall = [1_000_000.0]
        monotonic = [100.0]
        client = herdr.Herdr("scratch")
        self.herdr.last_action = client.last_action
        prompt = self.herdr.agent_prompt

        def command(argv, **kwargs):
            wall[0] = 996_400.0
            monotonic[0] += 1.0
            return SimpleNamespace(returncode=0, stdout='{"result": {}}', stderr="")

        def acting_prompt(target, text, **kwargs):
            client.run("agent", "prompt", target, text)
            self.herdr.last_action = client.last_action
            prompt(target, text, **kwargs)

        self.herdr.agent_prompt = acting_prompt
        a = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "first")
        b = self.store.add("general", "Orc", "REQUEST", "Coord-b", "b", "second")
        with (patch.object(scheduler, "ts", lambda: wall[0]),
              patch.object(herdr.time, "time", lambda: wall[0]),
              patch.object(scheduler.time, "monotonic", lambda: monotonic[0]),
              patch.object(herdr.subprocess, "run", side_effect=command),
              patch.object(scheduler, "plan", side_effect=[
                  [("deliver", "a", (a,)), ("deliver", "b", (b,))],
                  [("deliver", "b", (b,))]])):
            self.rt.tick()
            self.assertEqual([p[0] for p in self.herdr.prompts], ["a"])
            monotonic[0] = 102.0
            self.rt.tick()
        self.assertEqual([p[0] for p in self.herdr.prompts], ["a", "b"])

    def test_tick_close_waits_behind_earlier_close(self):
        self.track_actions()
        self.herdr.status.update(a="absent", b="absent")
        self.team.save_state({"a": {"status": "absent", "close_pane_at": 1},
                              "b": {"status": "absent", "close_pane_at": 1}})
        self.rt.tick()
        self.assertEqual(self.herdr.closed, ["p-a"])
        self.assertEqual(self.team.load_state()["b"]["close_pane_at"], 1)
        self.rt.tick()
        self.assertEqual(self.herdr.closed, ["p-a", "p-b"])

    def test_tick_alert_runs_after_action_but_later_delivery_waits(self):
        from unittest.mock import patch
        self.track_actions()
        calls = []
        def deliver(s, ids, st):
            calls.append(("deliver", s.key))
            self.herdr.agent_prompt(s.agent, "message")
        self.rt.deliver = deliver
        self.rt.alert = lambda s, minutes, st: calls.append(("alert", s.key))
        with patch("codeteam2.scheduler.plan", return_value=[("deliver", "a", (1,)), ("alert", "a", 3),
                                                            ("deliver", "b", (2,))]):
            self.rt.tick()
        self.assertEqual(calls, [("deliver", "a"), ("alert", "a")])

    def test_tick_without_last_action_runs_all_deliveries(self):
        from unittest.mock import patch
        a = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "first")
        b = self.store.add("general", "Orc", "REQUEST", "Coord-b", "b", "second")
        with patch("codeteam2.scheduler.plan", return_value=[("deliver", "a", (a,)), ("deliver", "b", (b,))]):
            self.rt.tick()
        self.assertEqual([p[0] for p in self.herdr.prompts], ["a", "b"])

    def test_tick_noop_delivery_does_not_hold_next_action(self):
        from unittest.mock import patch
        self.track_actions()
        calls = []
        def deliver(s, ids, st):
            calls.append(s.key)
            if s.key == "b":
                self.herdr.agent_prompt(s.agent, "message")
        self.rt.deliver = deliver
        with patch("codeteam2.scheduler.plan", return_value=[("deliver", "a", (1,)), ("deliver", "b", (2,))]):
            self.rt.tick()
        self.assertEqual(calls, ["a", "b"])
        self.assertEqual([p[0] for p in self.herdr.prompts], ["b"])

    def test_start_uses_fresh_labelled_pane_after_ensure(self):
        def ensure(session, ws):
            self.herdr.panes = lambda workspace: [{"pane_id": "new-pane", "label": "a", "tab_id": "t1"}]
            return "old-pane"
        self.rt.ensure_pane = ensure
        self.rt.start(self.team.session("a"), {})
        self.assertEqual([pane for pane, _ in self.herdr.runs], ["new-pane"])

    def test_start_renders_roles_first_when_the_lane_folder_has_no_claude(self):
        # a folder made by the lane's first message had no .claude, so its session exited.
        renders = []
        self.team.t.lane_dir = lambda key: Path(self.d.name) / "workcrews" / key
        (Path(self.d.name) / "workcrews" / "a").mkdir(parents=True)
        self.team.render_roles = lambda: renders.append(self.herdr.runs[:])
        self.rt.start(self.team.session("a"), {})
        self.assertEqual(renders, [[]])                     # rendered once, before anything ran in the pane
        self.assertEqual(len(self.herdr.runs), 1)

    def test_start_does_not_render_when_the_lane_folder_has_claude(self):
        renders = []
        self.team.t.lane_dir = lambda key: Path(self.d.name) / "workcrews" / key
        (Path(self.d.name) / "workcrews" / "a" / ".claude").mkdir(parents=True)
        self.team.render_roles = lambda: renders.append(1)
        self.rt.start(self.team.session("a"), {})
        self.assertEqual(renders, [])

    def test_a_render_error_never_stops_the_start(self):
        self.team.t.lane_dir = lambda key: Path(self.d.name) / "workcrews" / key
        def broken():
            raise RuntimeError("template missing")
        self.team.render_roles = broken
        self.rt.start(self.team.session("a"), {})
        self.assertEqual(len(self.herdr.runs), 1)

    def test_start_missing_label_raises_without_typing(self):
        from codeteam2.herdr import HerdrError
        def ensure(session, ws):
            self.herdr.panes = lambda workspace: []
            return "old-pane"
        self.rt.ensure_pane = ensure
        with self.assertRaises(HerdrError):
            self.rt.start(self.team.session("a"), {})
        self.assertEqual(self.herdr.runs, [])


class RunPacingTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import MagicMock
        self.team = SimpleNamespace(dir=MagicMock(), poll_s=30.0)
        self.herdr = SimpleNamespace(ensure_server=lambda _: None)
        self.logs = []
        self.rt = Runtime(self.team, log=self.logs.append, herdr=self.herdr, store=object())
        self.rt.manifest_mtime = lambda: None

    def run_for_sleeps(self, count):
        from unittest.mock import patch
        from codeteam2 import scheduler

        class StopRun(Exception):
            pass

        sleeps = []
        def sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) == count:
                raise StopRun()

        with (patch.object(scheduler, "open", create=True),
              patch.object(scheduler.fcntl, "flock"),
              patch.object(scheduler, "ts", return_value=1_000_000.0),
              patch.object(scheduler.time, "sleep", side_effect=sleep),
              self.assertRaises(StopRun)):
            self.rt.run()
        return sleeps

    def test_run_reobserves_three_due_deliveries_without_poll_delay(self):
        due = ["a", "b", "c"]
        delivered = []
        def tick():
            delivered.append(due.pop(0))
            self.rt.waited = len(due)
            return [], {}
        self.rt.tick = tick
        sleeps = self.run_for_sleeps(3)
        self.assertEqual(delivered, ["a", "b", "c"])
        self.assertEqual(sleeps, [1.0, 1.0, 30.0])
        self.assertLess(sum(sleeps), 90.0)

    def test_run_bounds_consecutive_quick_pauses_and_resets(self):
        def defer():
            self.rt.waited = 1
            return [], {}
        self.rt.tick = defer
        self.assertEqual(self.run_for_sleeps(12), [1.0] * 10 + [30.0, 1.0])

    def test_run_sleeps_full_poll_when_no_action_is_deferred(self):
        self.rt.tick = lambda: ([], {})
        self.assertEqual(self.run_for_sleeps(1), [30.0])

    def test_run_caps_quick_pause_at_poll_interval(self):
        self.team.poll_s = 0.5
        def defer():
            self.rt.waited = 1
            return [], {}
        self.rt.tick = defer
        self.assertEqual(self.run_for_sleeps(1), [0.5])
        self.team.poll_s = 30.0
        self.assertEqual(self.run_for_sleeps(1), [1.0])

    def test_run_sleeps_full_poll_after_error_before_action_loop(self):
        calls = []
        def defer_then_fail():
            calls.append(1)
            if len(calls) == 1:
                self.rt.waited = 1
                return [], {}
            raise ValueError("before action loop")
        self.rt.tick = defer_then_fail
        sleeps = self.run_for_sleeps(2)
        self.assertTrue(any("before action loop" in line for line in self.logs))
        self.assertEqual(sleeps, [1.0, 30.0])

    def test_run_quickly_retries_error_after_deferred_action(self):
        def defer_then_fail():
            self.rt.waited = 1
            raise ValueError("after action loop")
        self.rt.tick = defer_then_fail
        sleeps = self.run_for_sleeps(1)
        self.assertTrue(any("after action loop" in line for line in self.logs))
        self.assertEqual(sleeps, [1.0])


class RealTickRunTests(unittest.TestCase):
    """The real tick, alone and through run, with every dependency a fake: the store, herdr, the team's
    files, the clock and sleep. Each acting herdr call stamps last_action from the same counting clock that
    stamps observations, so an action always follows the observation it was planned from."""

    def setUp(self):
        from itertools import count
        from unittest.mock import patch
        from codeteam2 import scheduler
        self.team = FakeTeam("/fake-team", ["a", "b", "c"])
        self.team.dir = FakePath()
        self.team.poll_s = 30.0
        self.herdr = FakeHerdr({"a": "idle", "b": "idle", "c": "idle"})
        self.herdr.ensure_server = lambda _log: None
        self.store = FakeStore()
        self.logs = []
        self.rt = Runtime(self.team, log=self.logs.append, herdr=self.herdr, store=self.store)
        self.rt.workspace = lambda create=True: "w1"
        self.rt.manifest_mtime = lambda: None
        self.rt.transcript = lambda rec: None
        clock = count(2_000_000_000)
        self.now = lambda: float(next(clock))
        for target, name in ((scheduler, "ts"), (scheduler.time, "monotonic")):
            p = patch.object(target, name, self.now)
            p.start()
            self.addCleanup(p.stop)
        self.herdr.last_action = 0.0
        for name in ("agent_prompt", "pane_run", "pane_close", "pane_rename", "agent_rename"):
            def action(*args, _original=getattr(self.herdr, name), **kwargs):
                result = _original(*args, **kwargs)
                self.herdr.last_action = self.now()
                return result
            setattr(self.herdr, name, action)
        self.ids = [self.store.add("general", "Orc", "REQUEST", f"Coord-{k}", k, f"for {k}") for k in "abc"]

    def test_run_delivers_three_due_messages_in_three_ticks_with_quick_pauses(self):
        from unittest.mock import patch
        from codeteam2 import scheduler
        a, b, c = self.ids

        class StopRun(Exception):
            pass

        pauses = []
        def sleep(seconds):
            pauses.append(seconds)
            if len(pauses) == 3:
                raise StopRun()

        plans = [[("deliver", "a", (a,)), ("deliver", "b", (b,)), ("deliver", "c", (c,))],
                 [("deliver", "b", (b,)), ("deliver", "c", (c,))],
                 [("deliver", "c", (c,))]]
        with (patch.object(scheduler, "open", create=True),
              patch.object(scheduler.fcntl, "flock"),
              patch.object(scheduler, "plan", side_effect=plans),
              patch.object(scheduler.time, "sleep", side_effect=sleep),
              self.assertRaises(StopRun)):
            self.rt.run()
        self.assertEqual([p[0] for p in self.herdr.prompts], ["a", "b", "c"])
        self.assertEqual([self.store.get(m)["state"] for m in self.ids], ["delivered"] * 3)
        self.assertEqual(pauses, [1.0, 1.0, 30.0])
        self.assertEqual([line for line in self.logs if "tick error" in line], [])

    def test_tick_records_deferred_actions_then_clears_count(self):
        from unittest.mock import patch
        from codeteam2 import scheduler
        a, b, _ = self.ids
        with patch.object(scheduler, "plan", side_effect=[[("deliver", "a", (a,)), ("deliver", "b", (b,))],
                                                          [("deliver", "b", (b,))]]):
            self.rt.tick()
            self.assertEqual([p[0] for p in self.herdr.prompts], ["a"])
            self.assertEqual(self.rt.waited, 1)
            self.rt.tick()
        self.assertEqual([p[0] for p in self.herdr.prompts], ["a", "b"])
        self.assertEqual(self.rt.waited, 0)


class KilledStartTests(unittest.TestCase):
    def setUp(self):
        from codeteam2 import cli
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.team = DiskTeam(self.d.name, ["a", "b"])
        self.team.render_roles = lambda: None
        self.team.approve_dirs = lambda: 0
        self.team.halted = lambda: False
        for s in self.team.sessions():
            s.kind = "staff"
        self.herdr = FakeHerdr({"a": "absent", "b": "absent"})
        self.herdr.ensure_server = lambda _: False
        self.store = Store(Path(self.d.name) / "m.db")
        self.addCleanup(self.store.db.close)
        self.logs = []
        self.rt = Runtime(self.team, log=self.logs.append, herdr=self.herdr, store=self.store)
        self.rt.workspace = lambda create=True: "w1"
        self.cmd_up = cli.cmd_up
        self.args = SimpleNamespace(if_was_up=False, loop_only=False, targets=[], resume=False, no_loop=True)

    # integration: a real thread and timed waits on the real clock (wait 0.25 s, join 2 s)
    @integration_only
    def test_killed_start_reader_sees_complete_record(self):
        import threading
        mid = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "first prompt")
        snapshots = []
        finished = threading.Event()
        write_script = self.team.write_launch_script

        def read_state():
            snapshots.append(self.team.load_state())
            finished.set()

        reader = threading.Thread(target=read_state)

        def start_reader(*args, **kwargs):
            reader.start()
            finished.wait(0.25)
            return write_script(*args, **kwargs)

        self.team.write_launch_script = start_reader
        self.rt.start(self.team.session("a"), self.team.load_state())
        reader.join(timeout=2)
        self.assertFalse(reader.is_alive())
        self.assertEqual(snapshots[0].get("a", {}).get("sid"), "sid-1")
        self.assertEqual(snapshots[0]["a"].get("startup_mids"), [mid])
        self.assertEqual(self.store.get(mid)["state"], "delivered")

    def test_killed_start_during_pane_setup_allows_retry(self):
        from unittest import mock
        session = self.team.session("a")
        with mock.patch.object(self.rt, "ensure_pane", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.rt.start(session, self.team.load_state())
        self.assertFalse(self.team.load_state().get("a", {}).get("starting_at"))
        self.assertTrue(self.rt.start(session, self.team.load_state()))
        self.assertEqual([pane for pane, _ in self.herdr.runs], ["p-a"])

    def test_killed_start_up_persists_first_staff(self):
        def run(pane, command):
            if pane == "p-b":
                raise KeyboardInterrupt()
            self.herdr.runs.append((pane, command))

        self.herdr.pane_run = run
        with self.assertRaises(KeyboardInterrupt):
            self.cmd_up(self.team, self.rt, self.args)
        record = self.team.load_state().get("a", {})
        self.assertTrue(record.get("starting_at"))
        self.assertEqual(record.get("sid"), "sid-1")

    def test_killed_start_with_mail_is_recovered(self):
        from unittest import mock
        from codeteam2 import scheduler
        mid = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "first prompt")
        self.herdr.pane_run = lambda *_: (_ for _ in ()).throw(KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.rt.start(self.team.session("a"), self.team.load_state())
        record = self.team.load_state().get("a", {})
        self.assertTrue(record.get("starting_at"))
        self.assertEqual(record.get("startup_mids"), [mid])
        self.assertEqual(self.store.get(mid)["state"], "delivered")
        (self.team.dir / "down").write_text("down")
        with mock.patch.object(scheduler, "ts", return_value=record["starting_at"] + scheduler.START_GRACE_S + 1):
            self.rt.tick()
        self.assertEqual(self.store.get(mid)["state"], "queued")

    def test_killed_start_later_up_refuses_recent_start(self):
        self.team.save_state({"a": {"starting_at": time.time() - 10, "sid": "sid-existing"}})
        self.args.targets = ["a"]
        self.cmd_up(self.team, self.rt, self.args)
        self.assertEqual(self.herdr.runs, [])
        self.assertTrue(any("Coord-a: started" in line and "not started again" in line for line in self.logs))

    def test_killed_start_stale_tick_does_not_overwrite_start(self):
        newer = {"starting_at": time.time(), "sid": "sid-other", "startup_mids": []}
        self.rt.backup = lambda st, now: self.team.save_state({"a": newer.copy()})
        self.rt.tick()
        self.assertEqual(self.team.load_state().get("a", {}).get("sid"), "sid-other")
        self.assertEqual(self.team.load_state()["a"]["starting_at"], newer["starting_at"])
        self.assertEqual(self.herdr.runs, [])

    def test_killed_start_real_team_save_preserves_newer_start_and_wake(self):
        from codeteam2.team import Team
        team = object.__new__(Team)
        team.dir = Path(self.d.name)
        team.save_state({"a": {"sid": "new", "starting_at": 200, "startup_mids": [7], "wake_requested": 300}})
        team.save_state({"a": {"sid": "old", "starting_at": 100, "startup_mids": [3], "wake_requested": 150,
                               "status": "absent"}})
        rec = team.load_state()["a"]
        self.assertEqual((rec.get("sid"), rec.get("starting_at"), rec.get("startup_mids"),
                          rec.get("wake_requested"), rec.get("status")), ("new", 200, [7], 300, "absent"))

    def test_killed_start_gap_wake_only_merge(self):
        from codeteam2.team import Team
        team = object.__new__(Team)
        team.dir = Path(self.d.name)
        team.save_state({"a": {"starting_at": 100, "wake_requested": 200}})
        team.save_state({"a": {"starting_at": 100, "wake_requested": 120}})
        self.assertEqual(team.load_state()["a"]["wake_requested"], 200)

    def test_killed_start_gap_launch_keeps_concurrent_other_record(self):
        from codeteam2.cli import cmd_launch
        self.team.session("a").kind = "lane"
        observe = self.rt.observe
        newer = {"sid": "other-process", "starting_at": time.time()}

        def observe_with_start(ws):
            obs = observe(ws)
            self.team.save_state({"b": newer.copy()})
            return obs

        self.rt.observe = observe_with_start
        cmd_launch(self.team, self.rt, SimpleNamespace(targets=["a"], now=False, resume=False))
        disk = self.team.load_state()
        self.assertEqual(disk.get("b", {}).get("sid"), "other-process")
        self.assertTrue(disk.get("a", {}).get("wake_requested"))
        self.assertEqual(self.herdr.runs, [])

    def test_killed_start_gap_stale_tick_does_not_close_new_start_pane(self):
        now = time.time()
        self.team.save_state({"a": {"status": "absent", "starting_at": now - 1000,
                                    "close_pane_at": now - 1, "sid": "old"}})
        load = self.team.load_state
        first = [True]

        def load_then_start():
            st = load()
            if first[0]:
                first[0] = False
                self.team.save_state({"a": {"starting_at": now, "sid": "new"}})
            return st

        self.team.load_state = load_then_start
        self.rt.tick()
        self.assertFalse(self.herdr.closed)
        self.assertEqual(load()["a"]["sid"], "new")

    def test_killed_start_dropped_mail_not_in_prompt_or_record(self):
        mid = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "dropped task")
        pending = self.store.pending

        def drop_after_read(*args, **kwargs):
            messages = pending(*args, **kwargs)
            self.store.mark(mid, "dropped", "dropped before delivery")
            return messages

        self.store.pending = drop_after_read
        self.rt.start(self.team.session("a"), self.team.load_state())
        self.assertNotIn("dropped task", self.team.launched[1] or "")
        self.assertNotIn(mid, self.team.load_state().get("a", {}).get("startup_mids", []))
        self.assertEqual(self.store.get(mid)["state"], "dropped")


# A Claude Code screen's bottom, as herdr returns it with --format ansi (captured from the smoke team).
SCREEN_SUGGESTION = ("\x1b[0m\x1b[38;2;136;136;136m──────────────────────────── Orc-Smoke ─\x1b[0m\n"
                     "❯\xa0\x1b[0m\x1b[2mSmoke task 4\x1b[0m\n"
                     "\x1b[0m\x1b[38;2;136;136;136m──────────────────────────────────────\x1b[0m\n"
                     "  \x1b[0m\x1b[38;2;153;153;153m[Sonnet 5.5] smoke-project\x1b[0m\n")
SCREEN_TYPED = SCREEN_SUGGESTION.replace("\x1b[2mSmoke task 4", "please also check the")
SCREEN_EMPTY = SCREEN_SUGGESTION.replace("\x1b[2mSmoke task 4", "")

# The bottom of a Claude Code screen with its agent list below the input box, trimmed from two captures
# (2026-10-29, Coord-model-cost-analysis): the rules are shortened, the box, status and agent-list lines
# are as captured, lines end \r\n as herdr sends them. The shown view's row is marked ⏺ (bold), the
# others ◯ (greyed by colour, not SGR 2); `main` is the session's own conversation. In SCREEN_SUBAGENT_VIEW the pane shows
# request-lead's view: anything typed there goes to that agent, not to the session.
SCREEN_SUBAGENT_VIEW = (
    ("\x1b[0m\x1b[38;2;8;145;178m────────────────────────────────────────\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;8;145;178m Lead reviewer-replay request \x1b[0m\x1b[38;2;8;145;178m─\x1b[0m\r\n")
    + ("❯\xa0\x1b[0m\x1b[2mMessage @request-lead…\x1b[0m\r\n")
    + ("\x1b[0m\x1b[38;2;8;145;178m────────────────────────────────────────\x1b[0m\r\n")
    + ("  \x1b[0m\x1b[38;2;153;153;153m[Opus 5.5] 63k tok  $21.09  Effort: medium  Questions: 1\x1b[0m\r\n")
    + ("  \x1b[0m\x1b[38;2;153;153;153m-- INSERT --\x1b[0m \x1b[0m\x1b[38;2;255;107;128m⏵⏵ bypass permissions on\x1b[0m\x1b[38;2;153;153;153m (shift+tab to cycle) · ← 23 agents\x1b[0m\r\n")
    + ("\r\n")
    + ("\x1b[0m\x1b[38;2;153;153;153m  ◯ main\x1b[0m\r\n")
    + ("\x1b[0m\x1b[1m  ⏺ request-lead       Lead reviewer-replay request\x1b[0m" + " " * 147 + "\x1b[0m\x1b[1mwaiting\x1b[0m\r\n")
    + ("\x1b[0m\x1b[38;2;153;153;153m  └ ◯ change-reviewer\x1b[0m  \x1b[0m\x1b[38;2;153;153;153mRe-review reviewer-replay round 2\x1b[0m" + " " * 126 + "\x1b[0m\x1b[38;2;153;153;153m6m 54s · ↓ 85.2k tokens\x1b[0m")
)
SCREEN_MAIN_VIEW = (
    ("\x1b[0m\x1b[38;2;136;136;136m──────────────────────────────────────── Coord-model-cost-analysis ─\x1b[0m\r\n")
    + ("❯\xa0\r\n")
    + ("\x1b[0m\x1b[38;2;136;136;136m────────────────────────────────────────\x1b[0m\r\n")
    + ("  \x1b[0m\x1b[38;2;153;153;153m[Opus 5.5] 163k tok  $25.99  Effort: medium  Questions: 1\x1b[0m\r\n")
    + ("  \x1b[0m\x1b[38;2;153;153;153m-- INSERT --\x1b[0m \x1b[0m\x1b[38;2;255;107;128m⏵⏵ bypass permissions on\x1b[0m\x1b[38;2;153;153;153m (shift+tab to cycle) · ← 23 agents\x1b[0m\r\n")
    + ("  \r\n")
    + ("\x1b[0m\x1b[1m  ⏺ main\x1b[0m\r\n")
    + ("\x1b[0m\x1b[38;2;153;153;153m  ◯ request-lead (+1)  Lead calibrate-candidates" + " " * 150 + "waiting\x1b[0m\r\n")
    + ("\x1b[0m\x1b[38;2;153;153;153m  ◯ request-lead (+1)\x1b[0m  \x1b[0m\x1b[38;2;153;153;153mLead normcost-pushed\x1b[0m" + " " * 155 + "\x1b[0m\x1b[38;2;153;153;153mwaiting\x1b[0m")
)


def _record(kind, stamp, content=None, **extra):
    """One Claude Code transcript record, with the fields transcript_state reads."""
    r = {"type": kind, "timestamp": stamp, **extra}
    if content is not None:
        r["message"] = {"content": content}
    return r


def _jsonl(path, rows, mode="w"):
    with open(path, mode) as f:
        f.write("".join(json.dumps(r) + "\n" for r in rows))


# A long typed prompt as Claude Code 2.1.307 records it: wrapped in a pasted_content tag.
WRAPPED_PROMPT = ('<pasted_content id="189a"> [codeteam] 2 messages for you, oldest first:\n\n'
                  '#1 REQUEST from Orc to Coord-a:\nfirst\n\n#2 NOTE from Kong to Coord-a:\nsecond\n</pasted_content>')


class BundleRideAlongTests(unittest.TestCase):
    def test_ride_alongs_before_a_runtime_command_do_not_block_it(self):
        """Ride-alongs alone before a runtime command: the command goes next (2026-11-06, an orc stuck 3 h)."""
        items = [(1, NOW - 900, "REQUEST", 1), (2, NOW - 800, "REQUEST", 1), (3, NOW - 700, "RUNTIME", 0),
                 (4, NOW - 600, "NOTE", 0)]
        self.assertEqual(bundle(items, NOW, 0), (3,))
        # after it, the real message goes and the ride-alongs ride with it
        self.assertEqual(bundle([items[0], items[1], items[3]], NOW, 0), (4, 1, 2))

    def test_a_real_message_before_a_runtime_command_still_goes_first(self):
        items = [(1, NOW - 900, "REQUEST", 1), (2, NOW - 800, "NOTE", 0), (3, NOW - 700, "RUNTIME", 0)]
        self.assertEqual(bundle(items, NOW, 0), (2, 1))


class BetweenTurnsTests(unittest.TestCase):
    """A session herdr shows working because of a background agent it started, its own turn over, takes its
    mail (2026-10-29: coordinators with background leads were deaf for the leads' whole run)."""

    def test_plan_delivers_between_turns_and_nothing_else(self):
        pend = {"a": [(1, NOW - 5)]}
        acts = P(status={"a": "working"}, pending=pend, between_turns={"a"})
        self.assertEqual(delivered(acts, "a"), [(1,)])
        self.assertFalse(delivered(P(status={"a": "working"}, pending=pend), "a"))
        # never stopped for idleness or a swap: its background work is running
        acts = P(status={"a": "working"}, pending={}, between_turns={"a"}, idle_exit_min=1,
                 st={"a": {"state_since": NOW - 7200}})
        self.assertFalse([x for x in acts if x[0] == "stop"])

    def test_prompt_that_never_ran_is_put_back(self):
        st = {"a": {"awaiting_turn": True, "delivered_at": NOW - 60, "last_mids": [4]}}
        acts = P(status={"a": "working"}, pending={}, st=st, between_turns={"a"})
        self.assertIn(("redeliver", "a", [4]), [(x[0], x[1], list(x[2])) for x in acts if x[0] == "redeliver"])

    def test_transcript_state(self):
        from codeteam2.scheduler import transcript_state
        rows = [{"type": "user", "timestamp": "2026-10-29T22:00:00Z", "message": {"content": "[codeteam] #1 hi"}},
                {"type": "assistant", "timestamp": "2026-10-29T22:00:02Z", "message": {"content": [{"type": "text", "text": "ok"}]}},
                {"type": "system", "subtype": "turn_duration", "timestamp": "2026-10-29T22:00:03Z"}]
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write("\n".join(json.dumps(r) for r in rows) + "\n")
        state, prompt = transcript_state(f.name)
        self.assertEqual(state, "ended")
        self.assertAlmostEqual(prompt, dt.datetime(2026, 10, 29, 22, 0, tzinfo=dt.timezone.utc).timestamp())
        with open(f.name, "a") as g:      # a task notification starts a turn: in turn, and not our prompt
            g.write(json.dumps({"type": "user", "timestamp": "2026-10-29T22:05:00Z",
                                "message": {"content": "<task-notification>done</task-notification>"}}) + "\n")
        state, prompt2 = transcript_state(f.name)
        self.assertEqual((state, prompt2), ("in-turn", prompt))
        with open(f.name, "a") as g:      # then someone runs /mcp by hand: no turn
            g.write(json.dumps({"type": "user", "timestamp": "2026-10-29T22:06:00Z",
                                "message": {"content": "<local-command-stdout>Reconnected</local-command-stdout>"}}) + "\n")
        self.assertEqual(transcript_state(f.name)[0], "ended")
        os.unlink(f.name)

    def test_transcript_state_counts_a_pasted_codeteam_prompt(self):
        """A [codeteam] prompt Claude Code records wrapped in <pasted_content ...> is codeteam's prompt: its
        timestamp is the prompt epoch, whether the content is a string or a list of text blocks."""
        from codeteam2.scheduler import transcript_state
        t0 = dt.datetime(2026, 11, 1, 10, 0, 0, tzinfo=dt.timezone.utc).timestamp()
        t1 = dt.datetime(2026, 11, 1, 10, 10, 0, tzinfo=dt.timezone.utc).timestamp()
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "s.jsonl"
            _jsonl(path, [_record("user", "2026-11-01T10:00:00Z", WRAPPED_PROMPT),
                          _record("assistant", "2026-11-01T10:00:02Z", [{"type": "text", "text": "ok"}]),
                          _record("system", "2026-11-01T10:00:03Z", subtype="turn_duration")])
            self.assertEqual(transcript_state(str(path)), ("ended", t0))
            _jsonl(path, [_record("user", "2026-11-01T10:10:00Z", [{"type": "text", "text": WRAPPED_PROMPT}]),
                          _record("assistant", "2026-11-01T10:10:02Z", [{"type": "text", "text": "ok"}]),
                          _record("system", "2026-11-01T10:10:03Z", subtype="turn_duration")], mode="a")
            self.assertEqual(transcript_state(str(path)), ("ended", t1))

    def test_task_notification_and_other_pasted_content_do_not_move_the_prompt(self):
        """After a wrapped [codeteam] prompt, a task notification and a pasted_content that is not a [codeteam]
        prompt are turns of their own but not codeteam's prompt: the prompt epoch stays at the wrapped one."""
        from codeteam2.scheduler import transcript_state
        t0 = dt.datetime(2026, 11, 1, 10, 0, 0, tzinfo=dt.timezone.utc).timestamp()
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "s.jsonl"
            _jsonl(path, [_record("user", "2026-11-01T10:00:00Z", WRAPPED_PROMPT),
                          _record("assistant", "2026-11-01T10:00:02Z", [{"type": "text", "text": "ok"}]),
                          _record("system", "2026-11-01T10:00:03Z", subtype="turn_duration")])
            self.assertEqual(transcript_state(str(path)), ("ended", t0))
            _jsonl(path, [_record("user", "2026-11-01T10:05:00Z", "<task-notification>done</task-notification>")],
                   mode="a")
            self.assertEqual(transcript_state(str(path)), ("in-turn", t0))
            pasted = '<pasted_content id="c3">\nthe build log: [codeteam] is only in here\n</pasted_content>'
            _jsonl(path, [_record("user", "2026-11-01T10:06:00Z", pasted)], mode="a")
            self.assertEqual(transcript_state(str(path)), ("in-turn", t0))

    def test_idle_compaction_after_the_turn_keeps_it_between_turns(self):
        """An idle compaction summary leaves the preceding ended state visible to between_turns (the tail of
        a coordinator on 2026-11-08, whose mail was held 11 h while its background lead ran)."""
        from codeteam2.scheduler import transcript_state
        t0 = dt.datetime(2026, 11, 8, 10, 0, tzinfo=dt.timezone.utc).timestamp()
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "s-a.jsonl"
            _jsonl(path, [
                _record("user", "2026-11-08T10:00:00Z", WRAPPED_PROMPT),
                _record("assistant", "2026-11-08T10:00:02Z", [{"type": "text", "text": "Done"}]),
                _record("system", "2026-11-08T10:00:03Z", subtype="stop_hook_summary"),
                _record("system", "2026-11-08T10:00:04Z", subtype="turn_duration", pendingBackgroundAgentCount=1),
                *[{"type": kind} for kind in ("last-prompt", "custom-title", "agent-name", "agent-setting",
                                              "mode", "permission-mode", "atis-latch")],
                _record("system", "2026-11-08T10:05:00Z", subtype="compact_boundary",
                        content="Conversation compacted", compactMetadata={"trigger": "auto"}),
                {"type": "user", "timestamp": "2026-11-08T10:05:01Z", "isCompactSummary": True,
                 "isVisibleInTranscriptOnly": True, "message": {"role": "user", "content":
                 "This session is being continued from a previous conversation that ran out of context."}},
                *[{"type": "attachment", "attachment": {"type": kind}}
                  for kind in ("directory", "file", "reminder")],
                _record("system", "2026-11-08T10:05:02Z", subtype="informational",
                        content="Compacted while idle, before the prompt cache expired"),
                {"type": "last-prompt"}, {"type": "permission-mode"},
                {"type": "queue-operation", "operation": "enqueue", "timestamp": "2026-11-08T10:06:00Z"},
                {"type": "queue-operation", "operation": "remove", "timestamp": "2026-11-08T10:06:01Z"},
                {"type": "queue-operation", "operation": "enqueue", "timestamp": "2026-11-08T10:07:00Z"},
                {"type": "queue-operation", "operation": "remove", "timestamp": "2026-11-08T10:07:01Z"},
            ])
            self.assertEqual(transcript_state(str(path)), ("ended", t0))
            store = Store(Path(d) / "m.db")
            try:
                rt = Runtime(FakeTeam(d, ["a"]), log=lambda *_: None, herdr=FakeHerdr({"a": "working"}), store=store)
                rec = {"sid": "s-a", "transcript": str(path), "awaiting_turn": False, "delivered_at": t0}
                self.assertTrue(rt.between_turns("a", rec, NOW))
            finally:
                store.db.close()

    def test_compaction_inside_a_turn_stays_in_turn(self):
        """A compaction summary after a tool result leaves the transcript in-turn."""
        from codeteam2.scheduler import transcript_state
        t0 = dt.datetime(2026, 11, 8, 10, 0, tzinfo=dt.timezone.utc).timestamp()
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "s-a.jsonl"
            _jsonl(path, [
                _record("user", "2026-11-08T10:00:00Z", WRAPPED_PROMPT),
                _record("assistant", "2026-11-08T10:00:01Z",
                        [{"type": "tool_use", "id": "tool-1", "name": "Read", "input": {}}]),
                _record("user", "2026-11-08T10:00:02Z",
                        [{"type": "tool_result", "tool_use_id": "tool-1", "content": "result"}]),
                _record("system", "2026-11-08T10:00:03Z", subtype="compact_boundary",
                        content="Conversation compacted", compactMetadata={"trigger": "auto"}),
                {"type": "user", "timestamp": "2026-11-08T10:00:04Z", "isCompactSummary": True,
                 "isVisibleInTranscriptOnly": True, "message": {"role": "user", "content": "Summary"}},
            ])
            self.assertEqual(transcript_state(str(path)), ("in-turn", t0))

    def test_between_turns_clears_awaiting_for_a_queued_prompt(self):
        """A prompt typed during a turn joins Claude Code's queue: an enqueue record after the delivery clears
        awaiting_turn, so the prompt is not typed again when the turn ends (2026-11-06, one prompt three times). An
        enqueue from before the delivery does not."""
        t0 = dt.datetime(2026, 11, 6, 8, 25, 21, tzinfo=dt.timezone.utc).timestamp()
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "s-a.jsonl"
            _jsonl(path, [_record("user", "2026-11-06T08:00:00Z", "[codeteam] #1 NOTE from Orc to a:\nold"),
                          _record("system", "2026-11-06T08:03:02Z", subtype="turn_duration"),
                          {"type": "queue-operation", "operation": "enqueue", "timestamp": "2026-11-06T08:10:00Z"}])
            store = Store(Path(d) / "m.db")
            try:
                rt = Runtime(FakeTeam(d, ["a"]), log=lambda *_: None, herdr=FakeHerdr({"a": "working"}), store=store)
                rec = {"sid": "s-a", "transcript": str(path), "awaiting_turn": True, "delivered_at": t0}
                rt.between_turns("a", rec, NOW)
                self.assertTrue(rec["awaiting_turn"])          # the old enqueue is not this prompt
                _jsonl(path, [{"type": "queue-operation", "operation": "enqueue",
                               "timestamp": "2026-11-06T08:25:21.209Z"}], mode="a")
                rt.between_turns("a", rec, NOW)
                self.assertFalse(rec["awaiting_turn"])
            finally:
                store.db.close()

    def test_turn_grace_outlasts_a_prompt_hook_timeout(self):
        """Claude Code writes a prompt only after its UserPromptSubmit hooks, which may run their 30 s timeout."""
        from codeteam2 import scheduler
        self.assertGreater(scheduler.TURN_GRACE_S, 30)
        st = {"a": {"awaiting_turn": True, "delivered_at": NOW - 31, "last_mids": [4]}}
        self.assertFalse([x for x in P(status={"a": "working"}, pending={}, st=st, between_turns={"a"})
                          if x[0] == "redeliver"])

    def test_between_turns_clears_awaiting_for_a_wrapped_prompt_that_ran(self):
        """A delivered prompt that Claude Code recorded as <pasted_content ...> [codeteam] ran: the session's
        awaiting_turn clears, and once its turn has ended it counts as between turns."""
        t0 = dt.datetime(2026, 11, 1, 10, 0, 0, tzinfo=dt.timezone.utc).timestamp()
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "s-a.jsonl"
            _jsonl(path, [_record("user", "2026-11-01T10:00:00Z", WRAPPED_PROMPT),
                          _record("assistant", "2026-11-01T10:00:02Z", [{"type": "text", "text": "ok"}]),
                          _record("system", "2026-11-01T10:00:03Z", subtype="turn_duration")])
            store = Store(Path(d) / "m.db")
            try:
                rt = Runtime(FakeTeam(d, ["a"]), log=lambda *_: None, herdr=FakeHerdr({"a": "working"}), store=store)
                rec = {"sid": "s-a", "transcript": str(path), "awaiting_turn": True, "delivered_at": t0}
                self.assertTrue(rt.between_turns("a", rec, NOW))
                self.assertFalse(rec["awaiting_turn"])
            finally:
                store.db.close()

    def test_between_turns_clears_awaiting_when_a_delivered_compact_ran(self):
        """A /compact typed between turns is no [codeteam] prompt and joins no queue; Claude Code records it, and
        its output, only when the compaction ends. Those records clear awaiting_turn, and the session is between
        turns again (2026-11-12: a coordinator's /compact at 15:53:50Z was typed twice more and compacted
        twice). A task notification or a tool result after the delivery does not count as the command."""
        t0 = dt.datetime(2026, 11, 12, 15, 53, 50, tzinfo=dt.timezone.utc).timestamp()
        compact = "<command-name>/compact</command-name>\n<command-message>compact</command-message>"
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "s-a.jsonl"
            _jsonl(path, [_record("user", "2026-11-12T15:50:00Z", "[codeteam] #1 NOTE from Orc to a:\nold"),
                          _record("assistant", "2026-11-12T15:53:49Z", [{"type": "text", "text": "report"}]),
                          _record("system", "2026-11-12T15:53:50Z", subtype="turn_duration")])
            store = Store(Path(d) / "m.db")
            try:
                rt = Runtime(FakeTeam(d, ["a"]), log=lambda *_: None, herdr=FakeHerdr({"a": "working"}), store=store)
                rec = {"sid": "s-a", "transcript": str(path), "awaiting_turn": True, "delivered_at": t0 + 0.4}
                self.assertTrue(rt.between_turns("a", rec, NOW))
                self.assertTrue(rec["awaiting_turn"])          # still compacting: nothing written yet
                _jsonl(path, [_record("user", "2026-11-12T15:54:00Z", "<task-notification> lead done"),
                              _record("user", "2026-11-12T15:54:01Z",
                                      [{"type": "tool_result", "tool_use_id": "t", "content": "x"}]),
                              _record("user", "2026-11-12T15:54:02Z", "skill text", isMeta=True)], mode="a")
                rt.between_turns("a", rec, NOW)
                self.assertTrue(rec["awaiting_turn"])
                _jsonl(path, [
                    _record("system", "2026-11-12T15:54:24Z", subtype="compact_boundary",
                            content="Conversation compacted", compactMetadata={"trigger": "manual"}),
                    {"type": "user", "timestamp": "2026-11-12T15:54:24Z", "isCompactSummary": True,
                     "message": {"role": "user", "content": "This session is being continued"}},
                    _record("user", "2026-11-12T15:53:50Z", compact),
                    _record("user", "2026-11-12T15:54:24Z", "<local-command-stdout>Compacted</local-command-stdout>"),
                ], mode="a")
                self.assertTrue(rt.between_turns("a", rec, NOW))
                self.assertFalse(rec["awaiting_turn"])
            finally:
                store.db.close()

    def test_a_delivered_compact_gets_the_longer_grace(self):
        """A /compact awaiting its turn is not typed again after TURN_GRACE_S, only after COMPACT_GRACE_S; other
        prompts keep TURN_GRACE_S."""
        from codeteam2 import scheduler
        self.assertGreater(scheduler.COMPACT_GRACE_S, scheduler.TURN_GRACE_S)
        for compacting, waited, expect in ((True, scheduler.TURN_GRACE_S, False),
                                           (True, scheduler.COMPACT_GRACE_S, True),
                                           (False, scheduler.TURN_GRACE_S, True)):
            st = {"a": {"awaiting_turn": True, "delivered_at": NOW - waited, "last_mids": [4],
                        "compacting": compacting}}
            acts = P(status={"a": "working"}, pending={}, st=st, between_turns={"a"})
            self.assertEqual(bool([x for x in acts if x[0] == "redeliver"]), expect, (compacting, waited))


class ScreenTests(unittest.TestCase):
    def test_draft(self):
        from codeteam2 import screen
        self.assertEqual(screen.draft(SCREEN_SUGGESTION), "")           # Claude Code's faint suggestion
        self.assertEqual(screen.draft(SCREEN_EMPTY), "")
        self.assertEqual(screen.draft(SCREEN_TYPED), "please also check the")
        self.assertIsNone(screen.draft("no input box here\n"))
        two = SCREEN_TYPED.replace("please also check the\x1b[0m\n",
                                   "first line\x1b[0m\n  second line\x1b[0m\n")
        self.assertEqual(screen.draft(two), "first line second line")

    def test_api_error(self):
        from codeteam2 import screen
        self.assertIn("API Error", screen.api_error("⏺ done\n  ⎿  API Error: 529 Overloaded\n"))
        self.assertIsNone(screen.api_error("⏺ We talked about a 429 earlier.\n"))

    def test_agent_view(self):
        from codeteam2 import screen
        self.assertEqual(screen.agent_view(SCREEN_SUBAGENT_VIEW), "request-lead")
        self.assertIsNone(screen.agent_view(SCREEN_MAIN_VIEW))
        self.assertIsNone(screen.agent_view(SCREEN_SUGGESTION))           # no agent list, a faint suggestion
        self.assertIsNone(screen.agent_view(SCREEN_TYPED))
        # No agent list: Claude Code's faint `Message @<name>…` placeholder alone says whose view it is.
        faint = SCREEN_SUGGESTION.replace("Smoke task 4", "Message @kong…")
        self.assertEqual(screen.agent_view(faint), "kong")
        # The same words at normal intensity are a person's draft, not a view.
        typed = SCREEN_SUGGESTION.replace("\x1b[2mSmoke task 4", "Message @kong…")
        self.assertIsNone(screen.agent_view(typed))


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.team = FakeTeam(self.d.name, ["a", "b"])
        self.herdr = FakeHerdr({"a": "idle", "b": "working"})
        self.store = Store(Path(self.d.name) / "m.db")
        self.rt = Runtime(self.team, log=lambda *_: None, herdr=self.herdr, store=self.store)
        self.rt.workspace = lambda create=True: "w1"

    def tearDown(self):
        self.store.db.close()
        self.d.cleanup()

    def test_pane_closed_after_stopped_exit(self):
        """A session codeteam stopped loses its bare-shell pane a few seconds after it exits; one that
        exited on its own keeps it."""
        from unittest import mock
        from codeteam2 import scheduler
        clock = [1_000_000.0]
        with mock.patch.object(scheduler, "ts", lambda: clock[0]):
            self.rt.tick()
            self.team.state["a"]["stopping_at"] = clock[0]
            self.herdr.status["a"] = "absent"
            self.herdr.status["b"] = "absent"            # b exits by itself
            clock[0] += 1
            self.rt.tick()
            self.assertFalse(self.herdr.closed)          # not at once
            clock[0] += scheduler.PANE_CLOSE_DELAY_S
            self.rt.tick()
        self.assertEqual(self.herdr.closed, ["p-a"])

    def test_burst_is_one_prompt(self):
        m1 = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "first thing")
        m2 = self.store.add("a", "Kong", "NOTE", "Coord-a", "a", "second thing")
        self.rt.tick()
        self.assertEqual(len(self.herdr.prompts), 1)
        agent, text = self.herdr.prompts[0]
        self.assertEqual(agent, "a")
        self.assertTrue(text.startswith("[codeteam] 2 messages"), text)
        self.assertIn("first thing", text)
        self.assertIn("second thing", text)
        self.assertEqual({self.store.get(m)["state"] for m in (m1, m2)}, {"delivered"})
        self.assertEqual(self.team.state["a"]["last_mids"], [m1, m2])
        # nothing more until the turn shows
        self.rt.tick()
        self.assertEqual(len(self.herdr.prompts), 1)

    def test_nothing_started_or_typed_while_halted(self):
        self.team.halted = lambda: True
        self.herdr.status["b"] = "absent"
        m1 = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "waits")
        self.store.add("general", "Orc", "REQUEST", "Coord-b", "b", "waits too")
        self.rt.tick()
        self.assertEqual(self.herdr.prompts, [])
        self.assertIsNone(self.team.launched)
        self.assertEqual(self.store.get(m1)["state"], "queued")
        self.team.halted = lambda: False                     # the user lifts it
        self.rt.tick()
        self.assertEqual(len(self.herdr.prompts), 1)

    def test_nothing_typed_while_going_down(self):
        (Path(self.d.name) / "down").write_text("now\n")
        self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "too late")
        self.rt.tick()
        self.assertEqual(self.herdr.prompts, [])

    def test_working_session_waits(self):
        self.store.add("general", "Orc", "REQUEST", "Coord-b", "b", "later")
        self.rt.tick()
        self.assertEqual(self.herdr.prompts, [])

    def test_mail_held_while_someone_types(self):
        self.herdr.screen = SCREEN_TYPED
        m = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "x")
        self.rt.tick()
        self.assertEqual(self.herdr.prompts, [])
        self.assertEqual(self.store.get(m)["state"], "queued")
        self.assertTrue(self.team.state["a"]["draft_since"])
        self.herdr.screen = SCREEN_SUGGESTION                  # sent or cleared: only the suggestion is left
        self.rt.tick()
        self.assertEqual(len(self.herdr.prompts), 1)
        self.assertFalse(self.team.state["a"]["draft_since"])

    def test_ride_along_waits_for_real_mail(self):
        r = self.store.add("general", "codeteam", "REQUEST", "Coord-a", "a", "patrol lines", ride=True)
        self.rt.tick()
        self.assertEqual(self.herdr.prompts, [])               # never alone
        m = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "real work")
        self.rt.tick()
        self.assertEqual(len(self.herdr.prompts), 1)
        text = self.herdr.prompts[0][1]
        self.assertLess(text.index("real work"), text.index("patrol lines"))   # the reason for the wake first
        self.assertEqual({self.store.get(x)["state"] for x in (r, m)}, {"delivered"})

    def test_first_turn_seen_from_completed_turns(self):
        self.herdr.status["b"] = "absent"
        self.rt.start(self.team._sessions[1], self.team.state)
        self.herdr.status["b"] = "idle"           # its whole first turn ran between two polls
        self.herdr.completions = {"b": 1}
        self.rt.tick()
        self.assertTrue(self.team.state["b"]["first_turn_seen"])

    def test_mail_goes_in_the_first_prompt(self):
        self.herdr.status["b"] = "absent"
        m = self.store.add("general", "Orc", "REQUEST", "Coord-b", "b", "start on this")
        self.rt.tick()
        self.assertEqual(self.team.launched[0], "b")
        self.assertIn("start on this", self.team.launched[1])
        self.assertEqual(self.store.get(m)["state"], "delivered")
        # it never came up: the mail goes back in the queue, and the next start carries it again
        self.team.state["b"]["starting_at"] -= 1000
        self.rt.tick()
        self.assertEqual(len([r for r in self.herdr.runs if r[0] == "p-b"]), 2)
        self.assertEqual(self.team.state["b"]["startup_mids"], [m])
        self.assertIn("start on this", self.team.launched[1])


    def test_refused_prompt_holds_every_message(self):
        self.herdr.refuse = "agent_blocked"
        m1 = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "x")
        m2 = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "y")
        self.rt.tick()
        self.assertEqual({self.store.get(m)["state"] for m in (m1, m2)}, {"held"})

    def test_single_message_reply_names_its_sender(self):
        self.store.add("general", "Kong", "REQUEST", "Coord-a", "a", "look")
        self.rt.tick()
        text = self.herdr.prompts[0][1]
        self.assertTrue(text.startswith("[codeteam] #"), text)
        self.assertIn("ANSWER Kong", text)

    def test_no_typing_into_a_subagent_view(self):
        """While the pane shows a subagent's view, a prompt would go to that agent, not the session: nothing
        is typed, and the mail waits untouched for the main view."""
        self.herdr.screen = SCREEN_SUBAGENT_VIEW
        m = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "for the session, not its lead")
        self.rt.tick()
        self.assertEqual(self.herdr.prompts, [])
        self.assertEqual(self.store.get(m)["state"], "queued")
        self.assertEqual(self.store.get(m)["attempts"], 0)
        self.assertFalse(self.team.state["a"].get("awaiting_turn"))
        self.herdr.screen = SCREEN_MAIN_VIEW                   # someone went back to the main conversation
        self.rt.tick()
        self.assertEqual(len(self.herdr.prompts), 1)
        self.assertEqual(self.store.get(m)["state"], "delivered")
        # a subagent's view (where /exit would reach that agent, not the session): stop waits too
        self.herdr.screen = SCREEN_SUBAGENT_VIEW
        self.assertFalse(self.rt.stop(self.team._sessions[0], self.team.state))
        self.assertNotIn(("a", "/exit"), self.herdr.prompts)

    def test_hold_notifies_owner_only_with_mail_waiting(self):
        """A view or draft hold tells the owner only when real (not ride-along) mail is waiting, and then once."""
        self.team.draft_alert_min = 0
        a, b = self.team._sessions
        self.herdr.screen = SCREEN_SUBAGENT_VIEW
        self.assertFalse(self.rt.stop(a, self.team.state))
        self.assertEqual(self.herdr.notified, [])              # no mail: nothing to tell the owner
        self.store.add("general", "codeteam", "NOTE", "Coord-a", "a", "patrol lines", ride=True)
        self.assertFalse(self.rt.stop(a, self.team.state))
        self.assertEqual(self.herdr.notified, [])              # a ride-along alone is not mail waiting
        m = self.store.add("general", "Orc", "NOTE", "Coord-a", "a", "held one")
        self.store.mark(m, "held", "agent_blocked")
        self.assertFalse(self.rt.stop(a, self.team.state))
        self.assertEqual(self.herdr.notified, [])              # held mail: leaving the view does not release it
        self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "x")
        self.assertFalse(self.rt.stop(a, self.team.state))
        self.assertFalse(self.rt.stop(a, self.team.state))
        self.assertEqual(len(self.herdr.notified), 1)          # once per episode
        self.assertIn("Coord-a", " ".join(self.herdr.notified[0]))
        # a draft: a fresh episode on b, which has no mail
        self.herdr.screen = SCREEN_TYPED
        self.assertFalse(self.rt.stop(b, self.team.state))
        self.assertEqual(len(self.herdr.notified), 1)
        # real mail for b arrives while its draft holds: the owner is told once
        self.store.add("general", "Orc", "REQUEST", "Coord-b", "b", "y")
        self.assertFalse(self.rt.stop(b, self.team.state))
        self.assertEqual(len(self.herdr.notified), 2)
        draft_note = " ".join(self.herdr.notified[1])
        self.assertIn("Coord-b", draft_note)
        self.assertIn("unsent text", draft_note)

    def test_a_held_view_is_read_again_each_tick(self):
        """A lane recorded as held in a subagent's view has its screen read each tick, mail or not, so the record clears."""
        self.team.state = {"a": {"view": "request-lead", "view_since": time.time() - 60}}
        self.herdr.screen = SCREEN_MAIN_VIEW
        self.rt.tick()
        self.assertIsNone(self.team.state["a"].get("view"))

    def test_a_held_draft_is_read_again_each_tick(self):
        """A lane recorded with a draft has its screen read each tick, mail or not, so the record clears when the draft goes."""
        self.team.state = {"a": {"draft_since": time.time() - 60}}
        self.herdr.screen = SCREEN_MAIN_VIEW
        self.rt.tick()
        self.assertFalse(self.team.state["a"].get("draft_since"))

    def test_hold_clears_when_the_session_exits(self):
        """A session not running holds nothing: its view and draft records clear on every tick (a state file that
        already says absent too), and herdr's sidebar shows no hold for it."""
        t = time.time()
        self.herdr.status["a"] = "absent"                      # its pane is still there: the sidebar is updated
        self.team.state = {"a": {"status": "absent", "view": "request-lead", "view_since": t - 60,
                                 "view_alerted": True, "draft_since": t - 60, "draft_alerted": True}}
        self.rt.tick()
        rec = self.team.state["a"]
        for f in ("view", "view_since", "view_alerted", "draft_since", "draft_alerted"):
            self.assertFalse(rec.get(f), f)
        sent = [k for a, k in (self.herdr.metadata or []) if a and a[0] == "p-a"]
        self.assertTrue(sent)
        self.assertEqual(sent[-1]["tokens"]["hold"], "")

    def test_held_mail_waits_for_a_change(self):
        """Held mail is not prompted again tick after tick: it goes back to the queue when the session's
        herdr status changes (or it completes a turn)."""
        self.rt.tick()                                         # a's status is known (idle) before the mail
        m = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "x")
        self.store.mark(m, "held", "agent_blocked")
        self.rt.tick()
        self.rt.tick()
        self.assertEqual(self.herdr.prompts, [])
        self.assertEqual(self.store.get(m)["state"], "held")
        self.herdr.status["a"] = "working"
        self.rt.tick()
        self.herdr.status["a"] = "idle"
        self.rt.tick()
        self.assertEqual(len(self.herdr.prompts), 1)
        self.assertEqual(self.store.get(m)["state"], "delivered")

    def episode_notes(self):
        """The NOTEs to the orchestrator that a prompt started no turn."""
        rows = self.store.db.execute("SELECT body FROM messages WHERE target='orc' AND kind='NOTE'").fetchall()
        return [r["body"] for r in rows if "could not get" in r["body"]]

    def no_turn_notes(self, mid):
        """The no-turn NOTEs that name message mid (one NOTE may name several: "#5 (REQUEST from Orc), #6 (...)")."""
        return [b for b in self.episode_notes() if f"#{mid} (" in b]

    def patch_clock(self):
        """Patch the loop's clock; the one-item list it returns is the time, which the test advances. It starts an
        hour ahead of the real clock, so mail the store stamps with real time is old enough to be prompted."""
        from unittest import mock
        from codeteam2 import scheduler
        clock = [time.time() + 3600]
        patcher = mock.patch.object(scheduler, "ts", lambda: clock[0])
        patcher.start()
        self.addCleanup(patcher.stop)
        return clock

    def stuck_bundle(self, clock, n=3):
        """n messages to a, delivered as one prompt that starts no turn (the fake herdr runs none) three times:
        the third no-turn prompt holds them and starts the episode. Returns their ids."""
        from codeteam2 import scheduler
        mids = [self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", f"task {i}") for i in range(n)]
        for _ in range(3):
            self.rt.tick()                                  # the bundle is prompted
            clock[0] += scheduler.TURN_GRACE_S
            self.rt.tick()                                  # no turn after the grace: put back, or held
        return mids

    def test_no_turn_note_goes_once(self):
        s = self.team._sessions[0]
        m = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "x")
        for _ in range(3):
            self.store.mark(m, "delivered")
        self.rt.redeliver(s, [m], {"a": {"last_mids": [m], "awaiting_turn": True}})
        self.assertEqual(self.store.get(m)["state"], "held")
        self.assertEqual(len(self.no_turn_notes(m)), 1)
        # released, prompted, and again no turn: held again, and orc is not told a second time
        self.store.mark(m, "queued")
        self.store.mark(m, "delivered")
        self.rt.redeliver(s, [m], {"a": {"last_mids": [m], "awaiting_turn": True}})
        self.assertEqual(self.store.get(m)["state"], "held")
        self.assertEqual(len(self.no_turn_notes(m)), 1)

    def test_three_prompts_start_one_episode_with_one_note_and_one_notice(self):
        """Messages held after their third no-turn prompt: one NOTE to the orchestrator naming them all, one
        notice to the owner, and the session's episode starts."""
        s = self.team._sessions[0]
        m1 = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "x")
        m2 = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "y")
        for m in (m1, m2):
            for _ in range(3):
                self.store.mark(m, "delivered")
        self.rt.redeliver(s, [m1, m2], self.team.state)
        notes = self.episode_notes()
        self.assertEqual(len(notes), 1, notes)
        self.assertIn(f"#{m1} (", notes[0])
        self.assertIn(f"#{m2} (", notes[0])
        self.assertIn("three prompts started no turn", notes[0])
        self.assertEqual({self.store.get(m)["state"] for m in (m1, m2)}, {"held"})
        self.assertEqual(len(self.herdr.notified), 1)
        self.assertTrue(self.team.state["a"].get("no_turn"))

    def test_note_names_only_the_messages_it_newly_holds(self):
        """A message already named in an earlier episode is not named again: the next episode's NOTE names only
        the messages it newly holds."""
        clock = self.patch_clock()
        (m1,) = self.stuck_bundle(clock, n=1)
        self.herdr.status["a"] = "working"
        self.rt.tick()                                      # a status change ends the episode; m1 is queued again
        m2 = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "second")
        self.store.mark(m1, "delivered")
        for _ in range(3):
            self.store.mark(m2, "delivered")
        self.rt.redeliver(self.team._sessions[0], [m1, m2], self.team.state)
        notes = self.episode_notes()
        self.assertEqual(len(notes), 2, notes)
        self.assertIn(f"#{m2} (", notes[1])
        self.assertNotIn(f"#{m1} (", notes[1])
        self.assertEqual(len(self.herdr.notified), 2)

    def test_episode_of_already_named_messages_is_silent(self):
        """Messages already named in an earlier episode start a new episode with no NOTE and no notice to the owner."""
        clock = self.patch_clock()
        (m1,) = self.stuck_bundle(clock, n=1)
        self.assertEqual(len(self.herdr.notified), 1)       # the first episode told the owner once
        self.herdr.status["a"] = "working"
        self.rt.tick()
        self.store.mark(m1, "delivered")
        self.rt.redeliver(self.team._sessions[0], [m1], self.team.state)
        self.assertEqual(self.store.get(m1)["state"], "held")
        self.assertEqual(len(self.episode_notes()), 1)
        self.assertEqual(len(self.herdr.notified), 1)
        self.assertTrue(self.team.state["a"].get("no_turn"))

    def test_orchestrator_is_notified_without_a_note_to_itself(self):
        """The orchestrator's own held prompt tells the owner once, and no NOTE goes to the orchestrator about itself."""
        s = SimpleNamespace(key="orc", display="Orc-Fake", agent="orc", kind="staff")
        m = self.store.add("general", "Coord-a", "REQUEST", "Orc-Fake", "orc", "x")
        for _ in range(3):
            self.store.mark(m, "delivered")
        self.rt.redeliver(s, [m], self.team.state)
        self.assertEqual(len(self.herdr.notified), 1)
        self.assertEqual(self.episode_notes(), [])
        self.assertEqual(self.store.get(m)["state"], "held")
        self.assertTrue(self.team.state["orc"].get("no_turn"))

    def test_no_episode_unless_a_message_is_held(self):
        """A message under three tries is put back, and a dropped one (or one whose row changed after it was read)
        is left alone: none of them starts an episode, a NOTE or a notice."""
        from unittest import mock
        s = self.team._sessions[0]
        young = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "young")
        self.store.mark(young, "delivered")
        dropped = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "dropped")
        for _ in range(3):
            self.store.mark(dropped, "delivered")
        self.store.mark(dropped, "dropped")
        self.rt.redeliver(s, [young, dropped], self.team.state)
        self.assertEqual(self.store.get(young)["state"], "queued")
        self.assertEqual(self.store.get(dropped)["state"], "dropped")
        raced = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "raced")
        for _ in range(3):
            self.store.mark(raced, "delivered")
        stale = self.store.get(raced)                       # read as delivered ...
        self.store.mark(raced, "dropped")                   # ... then dropped before redeliver writes
        with mock.patch.object(self.store, "get", lambda mid, row=stale: row):
            self.rt.redeliver(s, [raced], self.team.state)
        self.assertEqual(self.store.get(raced)["state"], "dropped")
        self.assertFalse(self.team.state["a"].get("no_turn"))
        self.assertEqual(self.herdr.notified, [])
        self.assertEqual(self.episode_notes(), [])

    def test_held_recipient_gets_no_delivery_until_a_change(self):
        """While its episode lasts nothing is prompted to the session, whatever mail arrives: the new mail waits
        queued and the held mail stays in the store."""
        clock = self.patch_clock()
        mids = self.stuck_bundle(clock)
        new = [self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", f"later {i}") for i in (1, 2)]
        for _ in range(3):
            clock[0] += 60
            self.rt.tick()
        self.assertEqual(len(self.herdr.prompts), 3)
        self.assertEqual({self.store.get(m)["state"] for m in mids}, {"held"})
        self.assertEqual({self.store.get(m)["state"] for m in new}, {"queued"})
        self.assertEqual({m["id"] for m in self.store.pending("a", held=True)}, set(mids + new))

    def test_one_note_and_one_notice_across_many_ticks_and_messages(self):
        """Three held messages and two more arriving during the episode, over ten ticks: one NOTE to the
        orchestrator and one notice to the owner in all."""
        clock = self.patch_clock()
        self.stuck_bundle(clock)
        for i in (1, 2):
            self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", f"later {i}")
        for _ in range(10):
            clock[0] += 60
            self.rt.tick()
        self.assertEqual(len(self.episode_notes()), 1, self.episode_notes())
        self.assertEqual(len(self.herdr.notified), 1)

    def test_episode_ends_when_the_loop_restarts(self):
        """A loop restart is a new Runtime's first sighting of the session: the episode ends, the held mail is
        released, and it is prompted."""
        clock = self.patch_clock()
        mids = self.stuck_bundle(clock)
        new = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "later")
        self.rt.tick()
        self.assertEqual(len(self.herdr.prompts), 3)
        restarted = Runtime(self.team, log=lambda *_: None, herdr=self.herdr, store=self.store)
        restarted.workspace = lambda create=True: "w1"
        restarted.tick()
        self.assertEqual(len(self.herdr.prompts), 4)
        self.assertEqual({self.store.get(m)["state"] for m in mids + [new]}, {"delivered"})
        self.assertFalse(self.team.state["a"].get("no_turn"))

    def test_episode_ends_on_a_herdr_status_change(self):
        """A change in the session's herdr status ends the episode: the held mail is released, and prompted once
        the session is ready again."""
        clock = self.patch_clock()
        mids = self.stuck_bundle(clock)
        new = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "later")
        self.rt.tick()
        self.assertEqual(len(self.herdr.prompts), 3)
        self.herdr.status["a"] = "working"
        self.rt.tick()
        self.assertEqual({self.store.get(m)["state"] for m in mids}, {"queued"})
        self.herdr.status["a"] = "idle"
        self.rt.tick()
        self.assertEqual(len(self.herdr.prompts), 4)
        self.assertEqual({self.store.get(m)["state"] for m in mids + [new]}, {"delivered"})

    def test_episode_ends_on_a_completed_turn(self):
        """A turn completing on the session's terminal ends the episode: the held mail is released and prompted."""
        self.herdr.completions = {"a": 0}
        clock = self.patch_clock()
        mids = self.stuck_bundle(clock)
        new = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "later")
        self.rt.tick()
        self.assertEqual(len(self.herdr.prompts), 3)
        self.herdr.completions = {"a": 1}
        self.rt.tick()
        self.assertEqual(len(self.herdr.prompts), 4)
        self.assertEqual({self.store.get(m)["state"] for m in mids + [new]}, {"delivered"})

    def test_episode_ends_when_the_state_change_seq_moves(self):
        """herdr's state_change_seq moving from its value at the episode's start ends the episode."""
        clock = self.patch_clock()
        mids = self.stuck_bundle(clock)
        new = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "later")
        self.rt.tick()
        self.assertEqual(len(self.herdr.prompts), 3)
        self.herdr.seqs["a"] = 2
        self.rt.tick()
        self.assertEqual(len(self.herdr.prompts), 4)
        self.assertEqual({self.store.get(m)["state"] for m in mids + [new]}, {"delivered"})

    def test_a_seq_unknown_at_the_start_does_not_end_the_episode(self):
        """The state_change_seq comparison runs only when both values are known: an episode that began with no
        seq is not ended by a seq that shows up later."""
        self.herdr.seqs["a"] = None
        clock = self.patch_clock()
        mids = self.stuck_bundle(clock)
        new = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "later")
        self.herdr.seqs["a"] = 5
        self.rt.tick()
        self.rt.tick()
        self.assertEqual(len(self.herdr.prompts), 3)
        self.assertEqual({self.store.get(m)["state"] for m in mids}, {"held"})
        self.assertEqual(self.store.get(new)["state"], "queued")

    def test_episode_ends_on_a_codeteam_prompt_later_in_the_transcript(self):
        """A [codeteam] prompt written to the session's transcript after the episode began, here one wrapped as
        Claude Code wraps it, ends the episode. The held message whose header that prompt carries exactly (#1
        REQUEST from Orc to Coord-a) has run and is settled; the others (#2's header there names another kind
        and sender) are released and prompted with the mail that waited queued."""
        path = self.episode_transcript()
        clock = self.patch_clock()
        mids = self.stuck_bundle(clock)
        self.assertEqual(mids, [1, 2, 3])                   # WRAPPED_PROMPT contains headers for ids 1 and 2
        new = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "later")
        self.rt.tick()
        self.assertEqual(len(self.herdr.prompts), 3)
        attempts = self.store.get(mids[0])["attempts"]
        _jsonl(path, [_record("user", "2026-11-01T10:30:00Z", WRAPPED_PROMPT)], mode="a")
        self.rt.tick()
        self.assertEqual(len(self.herdr.prompts), 4)
        self.assertEqual(self.prompt_ids(self.herdr.prompts[3][1]), [mids[1], mids[2], new])
        self.assertEqual(self.store.get(mids[0])["attempts"], attempts)
        self.assertEqual({self.store.get(m)["state"] for m in mids + [new]}, {"delivered"})

    def test_episode_ends_on_a_turn_ending_in_the_transcript(self):
        """A session herdr keeps at working (a background lead) can still run turns of its own, here one a task
        notification started: a turn ending in its transcript after the episode began ends the episode and its
        held mail is prompted (2026-11-12: a coordinator's turn at 16:01Z left its mail held). The turn that
        ended before the episode does not."""
        path = self.episode_transcript()
        clock = self.patch_clock()
        mids = self.stuck_bundle(clock)
        self.rt.tick()
        self.assertEqual(len(self.herdr.prompts), 3)
        self.assertEqual({self.store.get(m)["state"] for m in mids}, {"held"})
        later = dt.datetime.fromtimestamp(clock[0] + 5, dt.timezone.utc).isoformat().replace("+00:00", "Z")
        _jsonl(path, [_record("user", later, "<task-notification> lead done"),
                      _record("system", later, subtype="turn_duration")], mode="a")
        self.rt.tick()
        self.assertEqual(len(self.herdr.prompts), 4)
        self.assertEqual({self.store.get(m)["state"] for m in mids}, {"delivered"})
        self.assertFalse(self.team.state["a"].get("no_turn"))

    def test_a_delivered_compact_is_not_typed_again_within_its_grace(self):
        """deliver marks a /compact runtime command as compacting: it is not put back after TURN_GRACE_S, so it
        is typed once, and the resume line queued behind it waits; other mail is not compacting."""
        from codeteam2 import scheduler
        clock = self.patch_clock()
        c = self.store.add("runtime", "codeteam", RUNTIME, "Coord-a", "a",
                           "/compact Keep the Refocus report and the handoff above verbatim as the working state.")
        resume = self.store.add("runtime", "codeteam", RUNTIME, "Coord-a", "a", "Compaction done. Carry on.")
        self.rt.tick()
        self.assertEqual([t for _, t in self.herdr.prompts], [self.store.get(c)["body"]])
        self.assertTrue(self.team.state["a"]["compacting"])
        clock[0] += scheduler.TURN_GRACE_S
        self.rt.tick()
        self.assertEqual(len(self.herdr.prompts), 1)
        self.assertEqual(self.store.get(c)["state"], "delivered")
        self.assertEqual(self.store.get(resume)["state"], "queued")
        clock[0] += scheduler.COMPACT_GRACE_S
        self.rt.tick()
        self.assertEqual(self.store.get(c)["state"], "queued")    # no compaction seen in all that time: put back
        mail = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "x")
        self.store.mark(c, "dropped")
        self.store.mark(resume, "dropped")
        self.rt.tick()
        self.assertEqual(self.store.get(mail)["state"], "delivered")
        self.assertFalse(self.team.state["a"]["compacting"])

    def episode_transcript(self):
        """A transcript for session a whose last [codeteam] prompt ran before the episode; its path."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "s-a.jsonl"
        _jsonl(path, [_record("user", "2026-11-01T10:00:00Z", "[codeteam] #1 an earlier prompt"),
                      _record("assistant", "2026-11-01T10:00:02Z", [{"type": "text", "text": "ok"}]),
                      _record("system", "2026-11-01T10:00:03Z", subtype="turn_duration")])
        self.team.state["a"] = {"sid": "s-a", "transcript": str(path)}
        return path

    @staticmethod
    def prompt_ids(text):
        """The message ids a prompt's headers name, in order."""
        import re
        return [int(i) for i in re.findall(r"(?:^|\[codeteam\] )#(\d+) \w+ from \S+ to \S+:", text, re.M)]

    def test_prompt_that_ran_settles_its_held_mail(self):
        """The bundle's own prompt shows up in the transcript after the episode began (Claude Code had queued it
        and then ran it): its held messages are delivered with their attempts as they were and are not prompted
        again; another held message of the session, which that prompt does not carry, is released and prompted."""
        path = self.episode_transcript()
        clock = self.patch_clock()
        mids = self.stuck_bundle(clock)
        ran = self.herdr.prompts[-1][1]
        extra = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "not in that prompt")
        self.store.mark(extra, "held", "agent_blocked")
        attempts = {m: self.store.get(m)["attempts"] for m in mids}
        _jsonl(path, [_record("user", "2026-11-01T10:30:00Z", ran)], mode="a")
        n = len(self.herdr.prompts)
        self.rt.tick()
        from codeteam2 import scheduler
        clock[0] += scheduler.TURN_GRACE_S
        self.rt.tick()
        self.assertEqual({m: self.store.get(m)["state"] for m in mids}, {m: "delivered" for m in mids})
        self.assertEqual({m: self.store.get(m)["attempts"] for m in mids}, attempts)
        later = [i for _, text in self.herdr.prompts[n:] for i in self.prompt_ids(text)]
        self.assertFalse(set(mids) & set(later), later)
        self.assertIn(extra, later)
        self.assertFalse(self.team.state["a"].get("no_turn"))

    def test_an_id_quoted_in_a_body_is_not_settled(self):
        """Only a header at a line start or right after "[codeteam] " names a message: held X's body quoting
        held Y's header mid-line leaves Y to be released and prompted, while X is settled."""
        path = self.episode_transcript()
        s = self.team._sessions[0]
        self.rt.tick()                                      # a is seen: the next tick is no loop start
        y = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "the earlier ask")
        x = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a",
                           f"re #{y} REQUEST from Orc to Coord-a: done as asked")
        self.store.mark(y, "held", "agent_blocked")
        for _ in range(3):
            self.store.mark(x, "delivered")
        self.rt.redeliver(s, [x], self.team.state)
        self.assertEqual({self.store.get(m)["state"] for m in (x, y)}, {"held"})
        attempts = self.store.get(x)["attempts"]
        _jsonl(path, [_record("user", "2026-11-01T10:30:00Z", self.rt.message_text(s, self.store.get(x)))],
               mode="a")
        n = len(self.herdr.prompts)
        self.rt.tick()
        self.assertEqual(self.store.get(x)["state"], "delivered")
        self.assertEqual(self.store.get(x)["attempts"], attempts)
        self.assertEqual([i for _, text in self.herdr.prompts[n:] for i in self.prompt_ids(text)], [y])
        self.assertEqual(self.store.get(y)["state"], "delivered")

    def test_a_header_with_another_kind_or_sender_is_not_settled(self):
        """A header names a held row only when id, kind, sender and recipient all match it: in the prompt that
        ran, #1's header matches and #1 is settled; #2's names another kind and #3's another sender, so those
        two are released and prompted."""
        path = self.episode_transcript()
        clock = self.patch_clock()
        m1, m2, m3 = self.stuck_bundle(clock)
        ran = (self.herdr.prompts[-1][1]
               .replace(f"#{m2} REQUEST from Orc to Coord-a:", f"#{m2} NOTE from Orc to Coord-a:")
               .replace(f"#{m3} REQUEST from Orc to Coord-a:", f"#{m3} REQUEST from Kong to Coord-a:"))
        self.assertEqual(self.prompt_ids(ran), [m1, m2, m3])
        attempts = self.store.get(m1)["attempts"]
        _jsonl(path, [_record("user", "2026-11-01T10:30:00Z", ran)], mode="a")
        n = len(self.herdr.prompts)
        self.rt.tick()
        self.assertEqual(self.store.get(m1)["attempts"], attempts)
        self.assertEqual([i for _, text in self.herdr.prompts[n:] for i in self.prompt_ids(text)], [m2, m3])
        self.assertEqual({self.store.get(m)["state"] for m in (m1, m2, m3)}, {"delivered"})

    def test_a_single_message_prompt_that_ran_settles_it(self):
        """The one-message prompt shape, "[codeteam] #N KIND from S to R:", names its message: it is settled
        and nothing is prompted."""
        path = self.episode_transcript()
        clock = self.patch_clock()
        (m,) = self.stuck_bundle(clock, n=1)
        ran = self.herdr.prompts[-1][1]
        self.assertTrue(ran.startswith(f"[codeteam] #{m} REQUEST from Orc to Coord-a:\n"), ran)
        attempts = self.store.get(m)["attempts"]
        _jsonl(path, [_record("user", "2026-11-01T10:30:00Z", ran)], mode="a")
        self.rt.tick()
        self.assertEqual(len(self.herdr.prompts), 3)
        self.assertEqual(self.store.get(m)["state"], "delivered")
        self.assertEqual(self.store.get(m)["attempts"], attempts)
        self.assertFalse(self.team.state["a"].get("no_turn"))

    def test_a_status_change_releases_all_held_mail_whatever_the_transcript(self):
        """A herdr status change is checked before the transcript: it ends the episode and releases every held
        message, those the transcript's later prompt names too, and all are prompted once the session is ready."""
        path = self.episode_transcript()
        clock = self.patch_clock()
        mids = self.stuck_bundle(clock)
        _jsonl(path, [_record("user", "2026-11-01T10:30:00Z", self.herdr.prompts[-1][1])], mode="a")
        self.herdr.status["a"] = "working"
        self.rt.tick()
        self.assertEqual({self.store.get(m)["state"] for m in mids}, {"queued"})
        self.herdr.status["a"] = "idle"
        self.rt.tick()
        self.assertEqual(len(self.herdr.prompts), 4)
        self.assertEqual(self.prompt_ids(self.herdr.prompts[3][1]), mids)

    def test_redeliver_leaves_a_dropped_message(self):
        s = self.team._sessions[0]
        m = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "x")
        self.store.mark(m, "delivered")
        self.store.mark(m, "dropped")
        self.rt.redeliver(s, [m], {"a": {"last_mids": [m], "awaiting_turn": True}})
        self.assertEqual(self.store.get(m)["state"], "dropped")
        self.assertEqual(self.no_turn_notes(m), [])

    def test_redeliver_does_not_resurrect_a_drop_after_its_read(self):
        """redeliver reads the row as delivered, then another process drops it before redeliver writes:
        the drop holds, and orc gets no NOTE."""
        from unittest import mock
        s = self.team._sessions[0]
        for attempts in (1, 3):
            m = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "x")
            for _ in range(attempts):
                self.store.mark(m, "delivered")
            stale = self.store.get(m)
            self.store.mark(m, "dropped")
            with mock.patch.object(self.store, "get", lambda mid, row=stale: row):
                self.rt.redeliver(s, [m], {"a": {"last_mids": [m], "awaiting_turn": True}})
            self.assertEqual(self.store.get(m)["state"], "dropped", attempts)
            self.assertEqual(self.no_turn_notes(m), [], attempts)

    def test_held_mail_released_when_the_loop_starts(self):
        """A loop start is a change: held mail for a lane that stays absent gets one more chance, and the
        lane is started with it, instead of waiting for a status change that never comes."""
        self.herdr.status["b"] = "absent"
        m = self.store.add("general", "Orc", "REQUEST", "Coord-b", "b", "held before the restart")
        self.store.mark(m, "held", "agent_blocked")
        self.rt.tick()
        self.assertIsNotNone(self.team.launched)
        self.assertEqual(self.team.launched[0], "b")
        self.assertIn("held before the restart", self.team.launched[1])
        self.assertEqual(self.store.get(m)["state"], "delivered")

    def test_loop_start_release_retried_after_it_fails(self):
        """A loop-start release that raises (sqlite "database is locked") does not mark the session seen:
        the next tick of the same Runtime releases the held mail and starts the absent lane with it."""
        import sqlite3
        from unittest import mock
        self.herdr.status["b"] = "absent"
        m = self.store.add("general", "Orc", "REQUEST", "Coord-b", "b", "held across a locked release")
        self.store.mark(m, "held", "agent_blocked")
        real, failed = self.store.release, []

        def release(k, why):
            if k == "b" and not failed:
                failed.append(k)
                raise sqlite3.OperationalError("database is locked")
            return real(k, why)
        with mock.patch.object(self.store, "release", release):
            with self.assertRaises(sqlite3.OperationalError):
                self.rt.tick()
            self.assertEqual(self.store.get(m)["state"], "held")
            self.rt.tick()
        self.assertEqual(failed, ["b"])
        self.assertIsNotNone(self.team.launched)
        self.assertEqual(self.team.launched[0], "b")
        self.assertIn("held across a locked release", self.team.launched[1])
        self.assertEqual(self.store.get(m)["state"], "delivered")


class RideAndExitPlanTests(unittest.TestCase):
    def test_ride_along_never_starts_or_wakes(self):
        ride = {"orc": [(1, NOW - 600, "REQUEST", 1)], "a": [(2, NOW - 600, "NOTE", 1)]}
        acts = P(status={"orc": "absent", "a": "absent"}, pending=ride)
        self.assertFalse([x for x in acts if x[0] == "start"])
        acts = P(status={"orc": "idle", "a": "idle"}, pending=ride)
        self.assertFalse([x for x in acts if x[0] == "deliver"])
        both = {"orc": [(1, NOW - 600, "REQUEST", 1), (3, NOW - 60, "NOTE", 0)]}
        self.assertEqual(delivered(P(status={"orc": "idle"}, pending=both), "orc"), [(3, 1)])

    def test_idle_exit(self):
        st = {"a": {"state_since": NOW - 7 * 3600}, "orc": {"state_since": NOW - 7 * 3600},
              "b": {"state_since": NOW - 3600}}
        acts = P(status={"a": "idle", "orc": "idle", "b": "idle"}, st=st, idle_exit_min=360, keep_awake={"orc"})
        self.assertIn(("stop", "a", "idle"), acts)
        self.assertFalse(stops(acts, "orc"))                  # the user talks to it
        self.assertFalse(stops(acts, "b"))                    # idle only an hour
        acts = P(status={"a": "idle"}, st=st, idle_exit_min=360, pending={"a": [(1, NOW, "NOTE", 0)]})
        self.assertFalse(stops(acts, "a"))                    # mail waiting
        self.assertFalse(stops(P(status={"a": "idle"}, st=st, idle_exit_min=0), "a"))
        self.assertFalse(stops(P(status={"a": "idle"}, st=st, idle_exit_min=360, held={"a"}), "a"))


class BackgroundWorkTests(unittest.TestCase):
    def test_background_work_is_not_ended_for_idleness(self):
        st = {"a": {"state_since": NOW - 7 * 3600, "bg_until": NOW + 600}}
        self.assertFalse([x for x in P(status={"a": "idle"}, st=st, idle_exit_min=360) if x[0] == "stop"])
        st["a"]["bg_until"] = NOW - 1                       # an hour later: idle exit may try again
        self.assertIn(("stop", "a", "idle"), P(status={"a": "idle"}, st=st, idle_exit_min=360))


class PatrolTests(unittest.TestCase):
    def test_only_new_findings(self):
        from codeteam2 import patrol
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "patrol.json"
            self.assertEqual(patrol.record(p, ["x: DEAD LEAD on r1"], 1), ["x: DEAD LEAD on r1"])
            self.assertEqual(patrol.record(p, ["x: DEAD LEAD on r1", "y: SERIAL"], 2), ["y: SERIAL"])
            self.assertEqual(patrol.latest(p), (2, ["x: DEAD LEAD on r1", "y: SERIAL"]))


class PluginTests(unittest.TestCase):
    """The herdr plugin layer: it acts only in a herdr session its teams use, and finds the team."""

    def setUp(self):
        import os
        from unittest import mock
        self.d = tempfile.TemporaryDirectory()
        root = Path(self.d.name)
        (root / "a.toml").write_text('product = "alpha"\n[v2]\nherdr_session = "codeteam"\n')
        (root / "b.toml").write_text('product = "beta"\n')                       # default session: codeteam
        (root / "c.toml").write_text('product = "gamma"\n[v2]\nherdr_session = "other"\n')
        (root / "cfg").mkdir()
        (root / "cfg" / "teams.toml").write_text(
            f'[[team]]\nmanifest = "{root}/a.toml"\nautostart = true\n'
            f'[[team]]\nmanifest = "{root}/b.toml"\n'
            f'[[team]]\nmanifest = "{root}/c.toml"\nautostart = true\n')
        self.env = mock.patch.dict(os.environ, {
            "HERDR_PLUGIN_CONFIG_DIR": str(root / "cfg"), "HERDR_SESSION": "",
            "HERDR_PLUGIN_STATE_DIR": str(root / "state"),
            "HERDR_SOCKET_PATH": "/home/x/.config/herdr/sessions/codeteam/herdr.sock",
            "HERDR_PLUGIN_CONTEXT_JSON": '{"workspace": {"workspace_id": "w2", "label": "beta"}}'})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.d.cleanup()

    def test_session_and_teams_here(self):
        from codeteam2 import plugin
        self.assertEqual(plugin.herdr_session_name(), "codeteam")
        self.assertEqual([p for _, p, _ in plugin.teams_here()], ["alpha", "beta"])   # not gamma: other session

    def test_focused_team_from_workspace_label(self):
        from codeteam2 import plugin
        self.assertTrue(plugin.focused_team().endswith("b.toml"))

    def test_startup_brings_back_autostart_teams_only(self):
        from unittest import mock
        from codeteam2 import plugin
        calls = []
        with mock.patch.object(plugin, "ct2", lambda *a, **k: calls.append((a, k)) or
                               SimpleNamespace(stdout="ok", stderr="", returncode=0)):
            result = plugin.cmd_startup(None)
        self.assertEqual(len(calls), 1)                     # alpha only: beta is not autostart, gamma elsewhere
        self.assertEqual(calls[0][0][0], "up")
        self.assertIn("--if-was-up", calls[0][0])
        self.assertEqual(result, 0)
        self.assertEqual(calls[0][1]["timeout"], plugin.STARTUP_UP_TIMEOUT_S)

    def test_startup_timeout_reaches_the_subprocess(self):
        from unittest import mock
        from codeteam2 import plugin
        self.assertEqual(plugin.STARTUP_UP_TIMEOUT_S, 900)
        with mock.patch.object(plugin.subprocess, "run",
                               return_value=SimpleNamespace(stdout="ok", stderr="", returncode=0)) as run:
            self.assertEqual(plugin.cmd_startup(None), 0)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.kwargs["timeout"], 900)
            plugin.ct2("status", "x", capture=True)
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args.kwargs["timeout"], 120)

    def test_startup_goes_on_after_a_failed_up(self):
        from unittest import mock
        from codeteam2 import plugin
        root = Path(self.d.name)
        (root / "delta.toml").write_text('product = "delta"\n[v2]\nherdr_session = "codeteam"\n')
        with (root / "cfg" / "teams.toml").open("a") as f:
            f.write(f'[[team]]\nmanifest = "{root}/delta.toml"\nautostart = true\n')
        with mock.patch.object(plugin, "ct2", side_effect=[
                SimpleNamespace(stdout="", stderr="up failed", returncode=1),
                SimpleNamespace(stdout="ok", stderr="", returncode=0)]) as ct2:
            result = plugin.cmd_startup(None)
        self.assertEqual([Path(call.args[1]).name for call in ct2.call_args_list], ["a.toml", "delta.toml"])
        self.assertEqual(result, 1)
        log = (root / "state" / "startup.log").read_text()
        self.assertIn("alpha: failed (exit 1): up failed", log)
        self.assertIn("delta: ok: ok", log)

    def test_startup_log_falls_back_to_home(self):
        import os
        from unittest import mock
        from codeteam2 import plugin
        home = Path(self.d.name) / "home"
        with mock.patch.dict(os.environ, {"HERDR_PLUGIN_STATE_DIR": ""}), \
                mock.patch.object(plugin.Path, "home", return_value=home), \
                mock.patch.object(plugin, "ct2", return_value=SimpleNamespace(stdout="ok", stderr="", returncode=0)):
            self.assertEqual(plugin.cmd_startup(None), 0)
        log = home / ".local" / "state" / "codeteam2" / "plugin-startup.log"
        self.assertTrue(log.is_file())
        self.assertIn("alpha: ok: ok", log.read_text())

    def test_startup_goes_on_when_the_log_is_unwritable(self):
        import contextlib
        import io
        import os
        from unittest import mock
        from codeteam2 import plugin
        root = Path(self.d.name)
        (root / "blocker").write_text("not a directory")
        (root / "delta.toml").write_text('product = "delta"\n[v2]\nherdr_session = "codeteam"\n')
        with (root / "cfg" / "teams.toml").open("a") as f:
            f.write(f'[[team]]\nmanifest = "{root}/delta.toml"\nautostart = true\n')
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"HERDR_PLUGIN_STATE_DIR": str(root / "blocker" / "state")}), \
                mock.patch.object(plugin, "ct2", return_value=SimpleNamespace(stdout="ok", stderr="", returncode=0)) as ct2, \
                contextlib.redirect_stdout(out):
            result = plugin.cmd_startup(None)
        self.assertEqual([Path(call.args[1]).name for call in ct2.call_args_list], ["a.toml", "delta.toml"])
        self.assertEqual(result, 0)
        self.assertIn("alpha: ok: ok", out.getvalue())
        self.assertIn("delta: ok: ok", out.getvalue())

    def test_startup_goes_on_after_a_team_times_out(self):
        import subprocess
        from unittest import mock
        from codeteam2 import plugin
        root = Path(self.d.name)
        (root / "delta.toml").write_text('product = "delta"\n[v2]\nherdr_session = "codeteam"\n')
        with (root / "cfg" / "teams.toml").open("a") as f:
            f.write(f'[[team]]\nmanifest = "{root}/delta.toml"\nautostart = true\n')
        calls = []

        def up(*args, **kwargs):
            calls.append(args)
            if len(calls) == 1:
                raise subprocess.TimeoutExpired(args, 900)
            return SimpleNamespace(stdout="ok", stderr="", returncode=0)

        with mock.patch.object(plugin, "ct2", side_effect=up):
            result = plugin.cmd_startup(None)
        self.assertEqual([Path(call[1]).name for call in calls], ["a.toml", "delta.toml"])
        self.assertEqual(result, 1)
        log = (root / "state" / "startup.log").read_text()
        self.assertTrue(any("alpha" in line and "failed" in line.lower() for line in log.splitlines()))
        self.assertTrue(any("delta" in line and "ok" in line.lower() for line in log.splitlines()))

    def test_startup_counts_a_failed_up(self):
        from unittest import mock
        from codeteam2 import plugin
        with mock.patch.object(plugin, "ct2", return_value=SimpleNamespace(stdout="", stderr="up failed", returncode=1)):
            result = plugin.cmd_startup(None)
        self.assertEqual(result, 1)
        log = (Path(self.d.name) / "state" / "startup.log").read_text()
        self.assertTrue(any("alpha" in line and "failed" in line.lower() for line in log.splitlines()))

    def test_nothing_outside_its_sessions(self):
        import os
        from unittest import mock
        from codeteam2 import plugin
        with mock.patch.dict(os.environ, {"HERDR_SOCKET_PATH": "/home/x/.config/herdr/herdr.sock"}):
            self.assertEqual(plugin.herdr_session_name(), "default")
            self.assertEqual(plugin.teams_here(), [])


class EntryPointTests(unittest.TestCase):
    # integration: runs bin/codeteam2 as a real process
    @integration_only
    def test_plugin_exit_status_reaches_the_shell(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            manifest = root / "broken.toml"
            manifest.write_text('product = "alpha"\n')  # Missing required repo and base.
            cfg = root / "cfg"
            cfg.mkdir()
            (cfg / "teams.toml").write_text(f'[[team]]\nmanifest = "{manifest}"\nautostart = true\n')
            env = dict(os.environ, HOME=str(root), HERDR_PLUGIN_CONFIG_DIR=str(cfg),
                       HERDR_PLUGIN_STATE_DIR=str(root / "state"), HERDR_SESSION="",
                       HERDR_SOCKET_PATH=str(root / "sessions" / "codeteam" / "herdr.sock"),
                       CODETEAM_HERDR_BIN="/usr/bin/false", HERDR_BIN_PATH="/usr/bin/false")
            exe = Path(__file__).resolve().parent.parent / "bin" / "codeteam2"
            result = subprocess.run([sys.executable, str(exe), "plugin", "startup"], env=env,
                                    capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    # integration: probes /usr/bin/python3 and, when it is pre-3.11, runs bin/codeteam2 as a real process
    @integration_only
    def test_runs_as_codeteam2_under_an_old_python(self):
        """With macOS's python3 (3.9) first on PATH, codeteam2 must re-run itself under a current Python,
        not end up running v1 (restart test, 2026-10-26)."""
        import os
        import subprocess
        old = "/usr/bin/python3"
        if not Path(old).exists() or subprocess.run([old, "-c", "import sys; sys.exit(sys.version_info >= (3, 11))"]).returncode:
            self.skipTest("no pre-3.11 python3 at /usr/bin")
        exe = Path(__file__).resolve().parent.parent / "bin" / "codeteam2"
        r = subprocess.run([str(exe), "--help"], capture_output=True, text=True, timeout=60,
                           env=dict(os.environ, PATH="/usr/bin:/bin:/usr/sbin:/sbin"))
        self.assertIn("usage: codeteam2", r.stdout + r.stderr)


class WarmTests(unittest.TestCase):
    def test_warm_follows_cache_lifetime(self):
        from codeteam2.team import default_warm_s
        self.assertEqual(default_warm_s("1h"), 3300)
        self.assertEqual(default_warm_s("5m"), 240)


class TabTests(unittest.TestCase):
    def test_orc_and_designer_together_other_staff_apart(self):
        team = SimpleNamespace(t=SimpleNamespace(assistants={"Designer-Acme": {"role": "designer"},
                                                             "Kong": {"role": "guard"}, "Nagatha": {}}))
        rt = Runtime.__new__(Runtime); rt.team = team
        S = lambda k, kind="staff": SimpleNamespace(key=k, kind=kind)
        self.assertEqual(rt.tab_of(S("orc")), "orc")
        self.assertEqual(rt.tab_of(S("Designer-Acme")), "orc")
        self.assertEqual(rt.tab_of(S("Kong")), "staff")
        self.assertEqual(rt.tab_of(S("Nagatha")), "staff")
        self.assertEqual(rt.tab_of(S("GearKit", "lane")), "GearKit")


class LaunchParityTests(unittest.TestCase):
    """v2 launches sessions with the same Claude Code settings as v1 (bin/codeteam write_launch_script):
    this fails when v1 gains a setting v2 does not pass (2026-10-25: v1 added the 1-hour cache and the
    auto mode prose, which v2 had missed)."""

    def stub(self, d):
        d = Path(d)
        (d / "launch").mkdir(exist_ok=True)
        return SimpleNamespace(isolate=False, m={}, home=d, root=d, team_file=d / "team.json", manifest="/m.toml",
                               env={}, ledger=lambda n: d / "ledger" / n, compact_window_of=lambda n: None,
                               effort_of=lambda n: None, lane_dir=lambda n: d, cmd=lambda v: f"codeteam {v}",
                               expand=lambda v: v, scratchpad=lambda n: d / "scratch" / n, ex_wt=lambda: d)

    def test_settings_keys_match_v1(self):
        import json
        import shlex
        from codeteam2.team import Team, v1
        with tempfile.TemporaryDirectory() as d:
            t = self.stub(d)
            script = v1.write_launch_script(t, "orc", d, "Orc-Test", "", Path(d) / "role.md", "", "claude-sonnet-5-5",
                                            "sid", False)
            words = shlex.split([ln for ln in script.read_text().splitlines() if "--settings" in ln][0])
            v1_settings = json.loads(words[words.index("--settings") + 1])
            team = object.__new__(Team)
            team.t = t
            v2_settings = team.launch_settings("orc", "Orc-Test")
        self.assertEqual(set(v2_settings), set(v1_settings))
        self.assertEqual(v2_settings["promptCacheTtl"], v1_settings["promptCacheTtl"])
        self.assertEqual(v2_settings["autoMode"], v1_settings["autoMode"])

    def launch_exports(self, d, key, kind):
        """The `export NAME=value` lines of the launch script v2 writes for one session."""
        import shlex
        from unittest.mock import patch
        from codeteam2.team import Session, v1
        t = self.stub(d)
        t.lab, t.isolate, t.repo_name, t.target = False, False, "repo", "main"
        team = object.__new__(Team)
        team.t, team.cfg, team.product, team.retry_watchdog = t, {"mcp": False}, "smoke", False
        team.dir = Path(d) / "v2"
        (team.dir / "launch").mkdir(parents=True, exist_ok=True)
        team.team_json = lambda: {"lanes": {"alpha": {"path": "pkg/alpha"}}}
        team.session_env = lambda k: {}
        team.ctx_env = lambda k, model: {}
        target = (Path(d), "Orc-Test" if key == "orc" else "Coord-alpha", "", Path(d) / "role.md", "", "")
        with patch.object(v1, "launch_target", return_value=target):
            path, _ = team.write_launch_script(Session(key, target[1], kind, key, Path(d)))
        out = {}
        for line in path.read_text().splitlines():
            if line.startswith("export ") and "=" in line:
                name, value = line[len("export "):].split("=", 1)
                out[name] = shlex.split(value)[0] if value else ""
        return out

    def test_every_session_gets_zone_mk_and_only_a_lane_gets_its_walls(self):
        """An orchestrator's or a staff session's work order tree builds and tests through zone.mk too
        (2026-11-12: an orc lead's tree had no zone targets until MAKEFILES was passed by hand). Only a lane
        names a lane worktree: CODETEAM_SWT is what turns the zone guard on."""
        from codeteam2.team import CT_HOME
        zone_mk = str(CT_HOME / "zone" / "zone.mk")
        with tempfile.TemporaryDirectory() as d:
            orc = self.launch_exports(d, "orc", "staff")
            lane = self.launch_exports(d, "alpha", "lane")
        self.assertEqual(orc.get("MAKEFILES"), zone_mk)
        self.assertNotIn("CODETEAM_SWT", orc)
        self.assertNotIn("CODETEAM_ZONE", orc)
        self.assertEqual(lane.get("MAKEFILES"), zone_mk)
        self.assertIn("CODETEAM_SWT", lane)
        self.assertEqual(lane.get("CODETEAM_ZONE"), "pkg/alpha")


class RoleRewriteTests(unittest.TestCase):
    """The role templates must carry no v1 watcher instruction (mail is delivered as [codeteam] prompts)."""

    def templates(self):
        roles = Path(__file__).resolve().parent.parent.parent / "roles"
        out = {}
        for f in sorted(roles.rglob("*.md")):
            text = f.read_text()
            for k, v in {"{{watch}}": "/x/codeteam2 watch /m.toml", "{{launch}}": "/x/codeteam2 launch /m.toml",
                         "{{lane}}": "alpha", "{{name}}": "Kong"}.items():
                text = text.replace(k, v)
            out[f.relative_to(roles).as_posix()] = text
        return out

    def test_templates_are_v2_native(self):
        """Since 2026-11-01 the templates say how mail arrives on v2 themselves; nothing is left for a rewrite."""
        from codeteam2.team import Team
        self.assertEqual(Team.REWRITES, [])
        for name, text in self.templates().items():
            self.assertIn("[codeteam]", text, name)

    def test_no_watcher_instruction_left(self):
        from codeteam2.team import Team
        for name, text in self.templates().items():
            new = Team.rewrite_role(text)
            for line in new.splitlines():
                if "codeteam watch` processes" in line:
                    continue            # the orchestrator's note on other teams' processes, not an instruction
                self.assertNotRegex(line, r"watch\b.*--now|[Rr]e-arm|start your watch|Your watch", f"{name}: {line[:120]}")


class StoreTests(unittest.TestCase):
    def test_lifecycle(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / "m.db")
            a = s.add("general", "Orc", "request", "Coord-a", "a", "do x")
            b = s.add("runtime", "codeteam", RUNTIME, "Coord-a", "a", "/compact")
            self.assertEqual([m["id"] for m in s.pending("a")], [a, b])
            s.mark(a, "delivered")
            self.assertEqual([m["id"] for m in s.pending("a")], [b])
            s.mark(b, "held", "agent_blocked")
            self.assertEqual([m["id"] for m in s.pending("a")], [])          # held: not the loop's to deliver
            self.assertEqual([m["id"] for m in s.pending("a", held=True)], [b])
            self.assertEqual(s.get(a)["kind"], "REQUEST")
            self.assertEqual(s.counts()["a"], {"delivered": 1, "held": 1})
            self.assertEqual([m["id"] for m in s.after(0)], [a])     # runtime commands are not team messages
            log = (Path(d) / "messages.log").read_text()
            self.assertIn("do x", log)
            self.assertNotIn("/compact", log)

    def test_drop_reports_per_id(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / "m.db")
            q, h, aw, dl, gone = (s.add("general", "Orc", "NOTE", "Coord-a", "a", f"m{i}") for i in range(5))
            s.mark(h, "held", "agent_blocked")
            s.mark(aw, "delivered")             # delivered, its turn not yet seen: still droppable
            s.mark(dl, "delivered")             # delivered and taken: it is the session's now
            s.drop([gone], "earlier")
            got = s.drop([q, h, aw, dl, gone, 9999], "by hand", awaiting={aw})
            self.assertEqual({k: got[k] for k in (q, h, aw)}, {q: "dropped", h: "dropped", aw: "dropped"})
            for mid in (dl, gone, 9999):
                self.assertIsInstance(got[mid], str)
                self.assertTrue(got[mid])
                self.assertNotEqual(got[mid], "dropped", mid)
            self.assertEqual(s.get(dl)["state"], "delivered")
            self.assertEqual(s.get(gone)["note"], "earlier")    # an already dropped row is left as it was
            self.assertEqual({s.get(x)["state"] for x in (q, h, aw, gone)}, {"dropped"})

    def test_mark_only_from_leaves_a_changed_row(self):
        """A write conditioned on the state the caller read does not overwrite a drop made since."""
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / "m.db")
            mid = s.add("general", "Orc", "NOTE", "Coord-a", "a", "x")
            s.mark(mid, "delivered")
            s.mark(mid, "dropped")
            s.mark(mid, "queued", only_from="delivered")
            self.assertEqual(s.get(mid)["state"], "dropped")

    def test_settle_held_delivers_only_the_targets_held_rows(self):
        """settle_held moves the target's held rows among the ids to delivered (delivered_at set, attempts as they
        were) and returns their ids in ascending order; a queued row, another target's held row and an unknown id are left."""
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / "m.db")
            h1, h2, queued = (s.add("general", "Orc", "NOTE", "Coord-a", "a", f"m{i}") for i in range(3))
            other = s.add("general", "Orc", "NOTE", "Coord-b", "b", "theirs")
            for mid in (h1, h2, other):
                s.mark(mid, "held", "no turn after 3 prompts")
            before = {mid: dict(s.get(mid)) for mid in (h1, h2, queued, other)}
            self.assertEqual(s.settle_held("a", [h2, queued, other, 9999, h1], "settled: its prompt ran"), [h1, h2])
            for mid in (h1, h2):
                row = s.get(mid)
                self.assertEqual(row["state"], "delivered")
                self.assertIsNotNone(row["delivered_at"])
                self.assertEqual(row["attempts"], before[mid]["attempts"])
            self.assertEqual(dict(s.get(queued)), before[queued])
            self.assertEqual(dict(s.get(other)), before[other])
            self.assertIsNone(s.get(9999))


class CliStatusTests(unittest.TestCase):
    """Status shows valid heartbeats and notes holds only for running sessions; state can be stale while down."""

    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.team = FakeTeam(self.d.name, ["a", "b"])
        self.team.halted = lambda: False
        self.store = Store(Path(self.d.name) / "m.db")
        self.rt = Runtime(self.team, log=lambda *_: None, herdr=FakeHerdr({"a": "absent", "b": "idle"}),
                          store=self.store)

    def tearDown(self):
        self.store.db.close()
        self.d.cleanup()

    def test_status_heartbeat_empty_is_absent(self):
        import contextlib
        import io
        from codeteam2.cli import cmd_status
        (self.team.dir / "heartbeat").write_text("")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                cmd_status(self.team, self.rt, SimpleNamespace())
            except (ValueError, OSError) as e:
                self.fail(f"cmd_status raised {type(e).__name__}: {e}")
        self.assertNotIn("(beat ", out.getvalue().splitlines()[0])

    def test_status_heartbeat_whitespace_is_absent(self):
        import contextlib
        import io
        from codeteam2.cli import cmd_status
        (self.team.dir / "heartbeat").write_text(" \t\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                cmd_status(self.team, self.rt, SimpleNamespace())
            except (ValueError, OSError) as e:
                self.fail(f"cmd_status raised {type(e).__name__}: {e}")
        self.assertNotIn("(beat ", out.getvalue().splitlines()[0])

    def test_status_heartbeat_garbage_is_absent(self):
        import contextlib
        import io
        from codeteam2.cli import cmd_status
        (self.team.dir / "heartbeat").write_text("12ab\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                cmd_status(self.team, self.rt, SimpleNamespace())
            except (ValueError, OSError) as e:
                self.fail(f"cmd_status raised {type(e).__name__}: {e}")
        self.assertNotIn("(beat ", out.getvalue().splitlines()[0])

    def test_status_heartbeat_unreadable_is_absent(self):
        import contextlib
        import io
        from codeteam2.cli import cmd_status
        (self.team.dir / "heartbeat").mkdir()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                cmd_status(self.team, self.rt, SimpleNamespace())
            except (ValueError, OSError) as e:
                self.fail(f"cmd_status raised {type(e).__name__}: {e}")
        self.assertNotIn("(beat ", out.getvalue().splitlines()[0])

    def test_status_heartbeat_valid_is_shown(self):
        import contextlib
        import io
        from codeteam2.cli import cmd_status
        (self.team.dir / "heartbeat").write_text(str(int(time.time()) - 5))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cmd_status(self.team, self.rt, SimpleNamespace())
        self.assertRegex(out.getvalue().splitlines()[0], r"\(beat \d+s ago\)")

    def test_status_shows_no_hold_for_a_session_not_running(self):
        import contextlib
        import io
        from codeteam2.cli import cmd_status
        t = time.time()
        rec = {"view": "request-lead", "view_since": t - 120, "draft_since": t - 120}
        self.team.state = {"a": dict(rec), "b": dict(rec)}
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cmd_status(self.team, self.rt, SimpleNamespace())
        lines = {k: next(x for x in out.getvalue().splitlines() if f"Coord-{k} " in x) for k in ("a", "b")}
        # the running session with the same record shows both notes: the gate, not a missing feature
        self.assertIn("TYPING", lines["b"])
        self.assertIn("VIEW", lines["b"])
        self.assertNotIn("TYPING", lines["a"])
        self.assertNotIn("VIEW", lines["a"])


class CliDropTests(unittest.TestCase):
    """`codeteam2 drop`: one line per id, a non-zero exit when any id was not dropped, and a dropped message
    that was awaiting its turn leaves the session's state so the loop does not put it back."""

    def setUp(self):
        import copy
        self.d = tempfile.TemporaryDirectory()
        self.team = FakeTeam(self.d.name, ["a", "b"])
        # cmd_drop must save what it changes: what it reads is a copy
        self.team.load_state = lambda: copy.deepcopy(self.team.state)
        self.store = Store(Path(self.d.name) / "m.db")
        self.rt = Runtime(self.team, log=lambda *_: None, herdr=FakeHerdr({"a": "idle", "b": "working"}),
                          store=self.store)

    def tearDown(self):
        self.store.db.close()
        self.d.cleanup()

    def drop(self, *ids):
        import contextlib
        import io
        from codeteam2.cli import cmd_drop
        out, code = io.StringIO(), None
        with contextlib.redirect_stdout(out):
            try:
                cmd_drop(self.team, self.rt, SimpleNamespace(ids=[f"#{i}" for i in ids], note=""))
            except SystemExit as e:
                code = e.code
        return out.getvalue(), code

    def test_reports_each_id_and_fails_when_one_is_not_dropped(self):
        q = self.store.add("general", "Orc", "NOTE", "Coord-a", "a", "waiting")
        dl = self.store.add("general", "Orc", "NOTE", "Coord-a", "a", "taken")
        self.store.mark(dl, "delivered")
        out, code = self.drop(q, dl)
        self.assertNotIn(code, (None, 0), out)
        lines = out.splitlines()
        self.assertEqual(len([ln for ln in lines if f"#{q}" in ln]), 1, out)
        dl_lines = [ln for ln in lines if f"#{dl}" in ln]
        self.assertEqual(len(dl_lines), 1, out)
        self.assertRegex(dl_lines[0], r"(?i)\bnot\b|delivered|cannot|can't", out)
        self.assertEqual(self.store.get(q)["state"], "dropped")
        self.assertEqual(self.store.get(dl)["state"], "delivered")

    def test_awaiting_message_leaves_the_session_state(self):
        aw = self.store.add("general", "Orc", "NOTE", "Coord-a", "a", "prompted, no turn yet")
        self.store.mark(aw, "delivered")
        self.team.state = {"a": {"last_mids": [aw], "awaiting_turn": True}}
        out, code = self.drop(aw)
        self.assertIn(code, (None, 0), out)
        self.assertEqual(self.store.get(aw)["state"], "dropped")
        self.assertEqual(self.team.state["a"]["last_mids"], [])
        self.assertFalse(self.team.state["a"]["awaiting_turn"])

    def test_repeated_id_is_dropped_once(self):
        q = self.store.add("general", "Orc", "NOTE", "Coord-a", "a", "waiting")
        out, code = self.drop(q, q)
        self.assertIn(code, (None, 0), out)
        self.assertEqual(self.store.get(q)["state"], "dropped")
        lines = [ln for ln in out.splitlines() if f"#{q}" in ln]
        self.assertTrue(lines, out)
        self.assertTrue(all("dropped (kept on record" in ln for ln in lines), out)


class CliAwaitTests(unittest.TestCase):
    """`codeteam2 await MANIFEST LANE FEATURE` records the wait as v1's cmd_await does: the lane must be in
    team.json, the feature goes through check_feature, and the lane's awaits file is sorted and de-duplicated.
    `codeteam2 await MANIFEST NAME` is watch's one-name form."""

    MANIFEST = "/m.toml"

    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        root = Path(self.d.name)
        self.team = FakeTeam(self.d.name, ["a", "b"])
        # v1's load_team reads team.json; v1's await_file reads t.ledger(lane) / "awaits.txt"
        (root / "team.json").write_text(json.dumps({"lanes": {"a": {}, "b": {}}}))
        self.team.t.team_file = root / "team.json"
        self.team.t.ledger = lambda n: root / n / "ledger"
        self.store = Store(root / "m.db")
        self.rt = Runtime(self.team, log=lambda *_: None, herdr=FakeHerdr({"a": "idle", "b": "idle"}),
                          store=self.store)

    def tearDown(self):
        self.store.db.close()
        self.d.cleanup()

    def run_cli(self, *argv):
        """Run codeteam2's main on the fake team and runtime. Returns (stdout, exit code, stderr)."""
        import contextlib
        import io
        from unittest.mock import patch
        from codeteam2.cli import main
        out, err, code = io.StringIO(), io.StringIO(), None
        with patch("codeteam2.cli.Team", return_value=self.team), \
                patch("codeteam2.cli.Runtime", return_value=self.rt), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                main(list(argv))
            except SystemExit as e:
                code = e.code
        return out.getvalue(), code, err.getvalue()

    def test_two_name_form_writes_the_awaits_file_sorted_and_without_repeats(self):
        from codeteam2.team import v1
        out, code, err = self.run_cli("await", self.MANIFEST, "a", "feat-b")
        self.assertIn(code, (None, 0), err)
        self.assertEqual(out, "a waits for feature feat-b; you are told when it is pushed\n")
        self.run_cli("await", self.MANIFEST, "a", "feat-a")
        out, code, err = self.run_cli("await", self.MANIFEST, "a", "feat-b")
        self.assertIn(code, (None, 0), err)
        self.assertEqual(v1.await_file(self.team.t, "a").read_text(), "feat-a\nfeat-b\n")

    def test_unknown_lane_is_refused_and_writes_no_awaits_file(self):
        from codeteam2.team import v1
        out, code, err = self.run_cli("await", self.MANIFEST, "zz", "f")
        self.assertIsInstance(code, str, f"exit code {code!r}, stderr: {err}")
        self.assertIn("unknown lane 'zz'", code)
        self.assertFalse(v1.await_file(self.team.t, "zz").exists())

    def test_one_name_form_prints_what_watch_prints_when_mail_is_queued(self):
        mid = self.store.add("general", "Orc", "NOTE", "Coord-a", "a", "waiting")
        watch_out, watch_code, watch_err = self.run_cli("watch", self.MANIFEST, "a", "--now")
        await_out, await_code, await_err = self.run_cli("await", self.MANIFEST, "a", "--now")
        self.assertIn(f"#{mid} NOTE from Orc", watch_out, watch_err)
        self.assertIn(await_code, (None, 0), await_err)
        self.assertEqual(await_out, watch_out)

    def test_one_name_form_says_nothing_waiting_when_no_mail_is_queued(self):
        watch_out, watch_code, watch_err = self.run_cli("watch", self.MANIFEST, "a", "--now")
        await_out, await_code, await_err = self.run_cli("await", self.MANIFEST, "a", "--now")
        self.assertIn("nothing waiting for Coord-a", watch_out, watch_err)
        self.assertIn(await_code, (None, 0), await_err)
        self.assertEqual(await_out, watch_out)


if __name__ == "__main__":
    unittest.main()


class TaskListFocusTests(unittest.TestCase):
    """The background-tasks list's selected row ("❯ ⏺ main") is not the input box (2026-11-05)."""

    def test_selected_task_row_is_not_a_draft(self):
        from codeteam2 import screen
        rule = "\x1b[0m\x1b[38;2;136;136;136m" + "─" * 40 + "\x1b[0m"
        box = "\x1b[0m\x1b[38;2;153;153;153m❯\xa0\x1b[0m\x1b[2mPress up to edit queued messages\x1b[0m"
        focused = "\n".join([rule, box, rule, "  -- INSERT -- ↑/↓ to select", "", "\x1b[0m\x1b[1m❯ ⏺ main\x1b[0m",
                             "  ◯ request-lead  lead   4h"])
        self.assertEqual(screen.draft(focused), "")
        self.assertTrue(screen.task_list_focused(focused))
        self.assertIsNone(screen.agent_view(focused))
        normal = focused.replace("\x1b[1m❯ ⏺ main", "  ⏺ main")
        self.assertFalse(screen.task_list_focused(normal))
        self.assertEqual(screen.draft(normal.replace("\x1b[2mPress up to edit queued messages", "hi")), "hi")
