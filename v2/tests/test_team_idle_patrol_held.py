"""Held lanes in patrol's team-idle and lane findings: team_idle leaves out a work order whose lane is held (a
held landing and an unheld lane's order stay open work), and patrol.findings drops a held lane's IDLE, ASLEEP,
DEAD LEAD, parked-row and SERIAL lines and passes the held set to stalled_work_orders and team_idle. v2's integration
group (rule 11, integration_module): real land records in temp folders."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2 import patrol  # noqa: E402
from codeteam2.team_idle import team_idle  # noqa: E402
from conftest import integration_module  # noqa: E402

pytestmark = integration_module

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
