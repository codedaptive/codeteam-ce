"""TEAM IDLE WITH WORK: patrol's line for a whole team stopped with open work, which wakes the orchestrator and tells
the owner once per episode.

unit tests (the unit group): TeamIdleTest and PatrolHeldTeamIdleTest run team_idle alone, over landing records in a temp
folder and sessions that are plain dicts; PatrolUnitTest runs Runtime.patrol with patrol.findings and patrol.record
faked; FindingsUnitTest and PatrolHeldFindingsTest run patrol.findings with its collaborators faked.
integration tests (integration_only, the integration group):
TeamIdleRecordTest joins team_idle with patrol.record's dedup, PatrolTellsOwnerTest joins
Runtime.patrol with the real patrol.record, and FindingsTest joins patrol.findings with the real team_idle."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2 import patrol, scheduler  # noqa: E402
from codeteam2.team_idle import team_idle  # noqa: E402
from conftest import integration_only  # noqa: E402

NOW = 2_000_000_000.0
HOUR_AGO = NOW - 3700


class LandFolder:
    """A land folder in a temp directory with work order records and queue entries, for team_idle."""

    def setUp(self):
        self.land = Path(tempfile.mkdtemp()) / "land"
        (self.land / "wo").mkdir(parents=True)
        (self.land / "queue").mkdir()

    def wo(self, name, **rec):
        (self.land / "wo" / f"{name}.json").write_text(json.dumps({"wo": name, "zone": "eventlog", **rec}))

    def entry(self, name, hold):
        (self.land / "queue" / f"{name}.json").write_text(json.dumps({"wo": name, "hold": hold}))

    def line(self, status, st):
        return team_idle(status, st, NOW, self.land)


class TeamIdleTest(LandFolder, unittest.TestCase):
    def test_a_team_idle_an_hour_with_an_open_work_order_is_reported(self):
        self.wo("rework")
        out = self.line({"Orc": "idle", "eventlog": "absent"},
                        {"Orc": {"state_since": HOUR_AGO}, "eventlog": {"state_since": NOW - 7200}})
        self.assertTrue(out.startswith("TEAM IDLE WITH WORK: no session of this team has worked since "))
        self.assertIn(time.strftime("%m-%d %H:%M", time.localtime(HOUR_AGO)), out)
        self.assertIn("while a work order is open or a queued landing is held", out)
        self.assertTrue(any(w in out for w in patrol.WAKES))

    def test_a_working_or_blocked_session_means_the_team_is_not_idle(self):
        self.wo("rework")
        for state in ("working", "blocked"):
            self.assertIsNone(self.line({"Orc": "idle", "eventlog": state},
                                        {"Orc": {"state_since": HOUR_AGO}, "eventlog": {"state_since": HOUR_AGO}}))

    def test_work_within_the_hour_is_not_idle(self):
        self.wo("rework")
        self.assertIsNone(self.line({"Orc": "idle", "eventlog": "idle"},
                                    {"Orc": {"state_since": HOUR_AGO}, "eventlog": {"state_since": NOW - 1800}}))

    def test_worked_at_comes_before_state_since(self):
        # A session put to sleep at 10 min ago had last worked 70 min ago: the team is idle since then.
        self.wo("rework")
        out = self.line({"Orc": "absent"}, {"Orc": {"state_since": NOW - 600, "worked_at": NOW - 4200}})
        self.assertIn(time.strftime("%m-%d %H:%M", time.localtime(NOW - 4200)), out)
        self.assertIsNone(self.line({"Orc": "idle"}, {"Orc": {"state_since": NOW - 7200, "worked_at": NOW - 600}}))

    def test_no_open_work_is_not_reported(self):
        self.wo("waiting", queued="2026-11-15T10:00:00-06:00")      # the runner's, not a session's
        self.wo("docs-stamp")                                       # the landing tool's own
        (self.land / "wo" / "old.landed.json").write_text(json.dumps({"wo": "old"}))
        (self.land / "wo" / "gone.retired.json").write_text(json.dumps({"wo": "gone"}))
        self.entry("waiting", hold=False)
        self.assertIsNone(self.line({"Orc": "idle"}, {"Orc": {"state_since": NOW - 7200}}))

    def test_a_held_landing_is_open_work(self):
        self.wo("squash", queued="2026-11-15T04:39:00-06:00")
        self.entry("squash", hold=True)
        self.assertIsNotNone(self.line({"Orc": "idle"}, {"Orc": {"state_since": NOW - 7200}}))

    def test_the_line_is_the_same_for_the_whole_episode(self):
        self.wo("rework")
        st = {"Orc": {"state_since": HOUR_AGO}}
        first = self.line({"Orc": "idle"}, st)
        self.assertEqual(team_idle({"Orc": "idle"}, st, NOW + 5 * 3600, self.land), first)

    def test_open_work_changing_within_an_episode_leaves_the_line_unchanged(self):
        # Patrol.record compares whole lines, so the line must not change when a held landing is released or a
        # work order is cut while nobody works.
        self.wo("one")
        self.wo("two")
        self.entry("squash", hold=True)
        st = {"Orc": {"state_since": HOUR_AGO}}
        first = self.line({"Orc": "idle"}, st)
        (self.land / "wo" / "two.json").unlink()
        self.entry("squash", hold=False)
        self.wo("fix-recheck-1")
        self.wo("fix-recheck-2")
        self.assertEqual(team_idle({"Orc": "idle"}, st, NOW + 1800, self.land), first)

    def test_no_sessions_or_no_times_say_nothing(self):
        self.wo("rework")
        self.assertIsNone(self.line({}, {}))
        self.assertIsNone(self.line({"Orc": "idle"}, {}))


class PatrolHeldTeamIdleTest(LandFolder, unittest.TestCase):
    def test_patrolheld_only_held_order_is_not_open_work(self):
        self.wo("rework")
        status, st = {"Orc": "idle"}, {"Orc": {"state_since": HOUR_AGO}}
        self.assertIsNotNone(team_idle(status, st, NOW, self.land))
        self.assertIsNone(team_idle(status, st, NOW, self.land, held=frozenset({"eventlog"})))

    def test_patrolheld_unheld_order_remains_open_work(self):
        self.wo("one", zone="eventlog")
        self.wo("two", zone="other")
        out = team_idle({"Orc": "idle"}, {"Orc": {"state_since": HOUR_AGO}}, NOW, self.land,
                        held=frozenset({"eventlog"}))
        self.assertTrue(out.startswith("TEAM IDLE WITH WORK:"))

    def test_patrolheld_landing_hold_remains_open_work(self):
        self.wo("squash", queued="2026-11-15T04:39:00-06:00")
        self.entry("squash", hold=True)
        out = team_idle({"Orc": "idle"}, {"Orc": {"state_since": HOUR_AGO}}, NOW, self.land,
                        held=frozenset({"eventlog"}))
        self.assertTrue(out.startswith("TEAM IDLE WITH WORK:"))


@integration_only
class TeamIdleRecordTest(LandFolder, unittest.TestCase):
    """integration test: team_idle's line through patrol.record, which decides what is new."""

    def test_open_work_changing_within_an_episode_is_not_new(self):
        # Kong: a held landing released or a work order cut while nobody works must not
        # make the line new, or the orchestrator is woken and the owner told a second time in one episode.
        self.wo("one")
        self.wo("two")
        self.entry("squash", hold=True)
        st = {"Orc": {"state_since": HOUR_AGO}}
        rec = Path(tempfile.mkdtemp()) / "patrol.json"
        self.assertEqual(len(patrol.record(rec, [self.line({"Orc": "idle"}, st)], NOW)), 1)
        (self.land / "wo" / "two.json").unlink()
        self.entry("squash", hold=False)
        self.wo("fix-recheck-1")
        self.wo("fix-recheck-2")
        self.assertEqual(patrol.record(rec, [team_idle({"Orc": "idle"}, st, NOW + 1800, self.land)], NOW + 1800), [])


def run_patrol(lines, fake_record):
    """Runtime.patrol over the given findings, with its store and herdr as stand-ins; fake_record: patrol.record is
    replaced by one that calls every line new. Returns (the store's (text, ride) adds, herdr's notifications)."""
    from unittest.mock import patch
    sent, told = [], []
    rt = object.__new__(scheduler.Runtime)
    rt.team = SimpleNamespace(patrol_min=30, dir=Path(tempfile.mkdtemp()), product="sprocket",
                              t=SimpleNamespace(orc_name=lambda: "Orc-Sprocket"))
    rt.store = SimpleNamespace(add=lambda *a, **k: sent.append((a[5], k.get("ride", False))))
    rt.log = lambda *a: None
    rt.herdr = SimpleNamespace(notify=lambda *a: told.append(a))
    with patch.object(scheduler.patrol_mod, "findings", lambda *a: lines):
        if fake_record:
            with patch.object(scheduler.patrol_mod, "record", lambda path, found, now=None: list(found)):
                rt.patrol({}, {}, NOW)
        else:
            rt.patrol({}, {}, NOW)
    return sent, told


TEAM_LINE = "TEAM IDLE WITH WORK: no session of this team has worked since 11-15 04:43 (over 60 min) while ..."
LANE_LINE = "eventlog: IDLE WITH WORK, idle 40 min, 1 queued (r1)"


class PatrolUnitTest(unittest.TestCase):
    """unit test: Runtime.patrol alone; what is new comes from a fake patrol.record."""

    def test_team_idle_wakes_the_orchestrator_and_tells_bob(self):
        sent, told = run_patrol([TEAM_LINE], fake_record=True)
        self.assertEqual([ride for t, ride in sent if TEAM_LINE in t], [False])
        self.assertEqual(told, [("codeteam sprocket: the team is idle with open work", TEAM_LINE)])

    def test_a_lane_idle_with_work_tells_only_the_orchestrator(self):
        sent, told = run_patrol([LANE_LINE], fake_record=True)
        self.assertEqual(len(sent), 1)
        self.assertEqual(told, [])


@integration_only
class PatrolTellsOwnerTest(unittest.TestCase):
    """integration test: Runtime.patrol with the real patrol.record."""

    def run_patrol(self, lines):
        return run_patrol(lines, fake_record=False)

    def test_team_idle_wakes_the_orchestrator_and_tells_bob(self):
        line = "TEAM IDLE WITH WORK: no session of this team has worked since 11-15 04:43 (over 60 min) while ..."
        sent, told = self.run_patrol([line])
        self.assertEqual([(t, ride) for t, ride in sent if line in t], [(sent[0][0], False)])
        self.assertEqual(told, [("codeteam sprocket: the team is idle with open work", line)])

    def test_a_lane_idle_with_work_tells_only_the_orchestrator(self):
        sent, told = self.run_patrol(["eventlog: IDLE WITH WORK, idle 40 min, 1 queued (r1)"])
        self.assertEqual(len(sent), 1)
        self.assertEqual(told, [])


class FindingsTeam:
    """A v5 team for patrol.findings: a land folder with one open work order, and a halted or ending marker."""

    def team(self, halted=False, down=False, lanes=None):
        root = Path(tempfile.mkdtemp())
        (root / "land" / "wo").mkdir(parents=True)
        (root / "land" / "wo" / "rework.json").write_text(json.dumps({"wo": "rework", "zone": "eventlog"}))
        tdir = root / "team-v2"
        tdir.mkdir()
        if down:
            (tdir / "down").write_text("")
        v1t = SimpleNamespace(root=root, manifest="m.toml", lab=False)
        return SimpleNamespace(t=v1t, team_json=lambda: {"lanes": lanes or {}}, dir=tdir, manifest="m.toml",
                               halted=lambda: halted, held=lambda k: False)

    def findings(self, team):
        store = SimpleNamespace(pending=lambda held=True: [])
        from unittest.mock import patch
        with patch.object(patrol, "running_lands", lambda m: set()), \
                patch("codeteam2.team.v1.branch_leftovers", lambda t, tj: ([], [], [])):
            return patrol.findings(team, {"Orc": "idle"}, {"Orc": {"state_since": NOW - 7200}}, store, NOW)


class FindingsUnitTest(FindingsTeam, unittest.TestCase):
    """unit test: patrol.findings with team_idle faked: it asks team_idle about the team's land folder and adds its line,
    and never asks for a halted or ending team."""

    def findings_with(self, team):
        from unittest.mock import patch
        asked = []

        def fake(status, st, now, land, held=frozenset()):
            asked.append((land, held))
            return "TEAM IDLE WITH WORK: fake"
        with patch.object(patrol, "team_idle", fake):
            return self.findings(team), asked

    def test_an_idle_v5_team_gets_the_line(self):
        team = self.team()
        lines, asked = self.findings_with(team)
        self.assertIn("TEAM IDLE WITH WORK: fake", lines)
        self.assertEqual(asked, [(team.t.root / "land", frozenset())])

    def test_a_halted_or_ending_team_does_not(self):
        for team in (self.team(halted=True), self.team(down=True)):
            lines, asked = self.findings_with(team)
            self.assertNotIn("TEAM IDLE WITH WORK: fake", lines)
            self.assertEqual(asked, [])


class PatrolHeldFindingsTest(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "land" / "wo").mkdir(parents=True)
        self.held = {"alpha"}
        self.team = SimpleNamespace(t=SimpleNamespace(root=root, lab=False, m={}), dir=root,
                                    manifest="fake.toml", team_json=lambda: {"lanes": {"alpha": {}}},
                                    held=lambda k: k in self.held)
        self.store = SimpleNamespace(pending=lambda held=True: [])
        self.work = ([['r', 'x', '-']], [], [], 0, ['r1'])
        self.lane = patch("codeteam2.team.v1.lane_work", side_effect=lambda *a: self.work)
        self.lane.start()
        self.addCleanup(self.lane.stop)
        for target, result in (("codeteam2.team.v1.branch_leftovers", ([], [], [], 0, 0, 0)),
                               ("codeteam2.patrol.running_lands", set()),
                               ("codeteam2.patrol.waiting_reviews", []),
                               ("codeteam2.patrol.stalled_work_orders", []),
                               ("codeteam2.patrol.team_idle", None)):
            p = patch(target, return_value=result)
            p.start()
            self.addCleanup(p.stop)

    def lines(self, status):
        return patrol.findings(self.team, status, {"alpha": {"state_since": NOW - 7200}}, self.store, NOW)

    def test_patrolheld_awake_lane_has_no_idle_with_work(self):
        self.held.clear()
        self.assertTrue(any("alpha: IDLE WITH WORK" in line for line in self.lines({"alpha": "idle"})))
        self.held.add("alpha")
        self.assertFalse(any("alpha: IDLE WITH WORK" in line for line in self.lines({"alpha": "idle"})))

    def test_patrolheld_absent_lane_has_no_asleep_with_work(self):
        self.held.clear()
        self.assertTrue(any("alpha: ASLEEP WITH WORK" in line for line in self.lines({})))
        self.held.add("alpha")
        self.assertFalse(any("alpha: ASLEEP WITH WORK" in line for line in self.lines({})))

    def test_patrolheld_lane_has_no_dead_lead_or_parked_rows(self):
        self.work = ([['r', 'x', '-']], [], ['r1'], 2, [])
        self.held.clear()
        lines = self.lines({"alpha": "idle"})
        self.assertTrue(any("alpha: DEAD LEAD" in line for line in lines))
        self.assertTrue(any("alpha: 2 ledger row(s) past queued" in line for line in lines))
        self.held.add("alpha")
        lines = self.lines({"alpha": "idle"})
        self.assertFalse(any("alpha: DEAD LEAD" in line or "past queued" in line for line in lines))

    def test_patrolheld_lane_has_no_serial_line(self):
        self.work = ([['r', 'x', '-']], [], [], 0, ['r1', 'r2'])
        self.held.clear()
        self.assertTrue(any("alpha: SERIAL" in line for line in self.lines({"alpha": "working"})))
        self.held.add("alpha")
        self.assertFalse(any("alpha: SERIAL" in line for line in self.lines({"alpha": "working"})))

    def test_patrolheld_removing_hold_restores_line_next_round(self):
        first = self.lines({})
        self.held.clear()
        second = self.lines({})
        self.assertFalse(any("alpha: ASLEEP WITH WORK" in line for line in first))
        self.assertTrue(any("alpha: ASLEEP WITH WORK" in line for line in second))

    def test_patrolheld_findings_passes_held_to_stalled_check(self):
        from unittest.mock import patch
        with patch.object(patrol, "stalled_work_orders", return_value=[]) as stalled:
            self.lines({})
        self.assertEqual(stalled.call_args.kwargs.get("held"), frozenset({"alpha"}))

    def test_patrolheld_findings_passes_held_to_team_idle(self):
        from unittest.mock import patch
        with patch.object(patrol, "team_idle", return_value=None) as idle:
            self.lines({})
        self.assertEqual(idle.call_args.kwargs.get("held"), frozenset({"alpha"}))


@integration_only
class FindingsTest(FindingsTeam, unittest.TestCase):
    """integration test: patrol.findings with the real team_idle adds the line for a v5 team, and never for a halted or ending one."""

    def test_an_idle_v5_team_gets_the_line(self):
        self.assertTrue(any(x.startswith("TEAM IDLE WITH WORK") for x in self.findings(self.team())))

    def test_a_halted_or_ending_team_does_not(self):
        for team in (self.team(halted=True), self.team(down=True)):
            self.assertFalse(any(x.startswith("TEAM IDLE WITH WORK") for x in self.findings(team)))


if __name__ == "__main__":
    unittest.main()
