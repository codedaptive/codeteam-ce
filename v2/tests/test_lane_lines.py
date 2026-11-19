"""lane_lines: the patrol's lines for one lane (D580's extraction from patrol.findings). Unit tests: v1's lane_work,
landing and PATROL_DEAD_MIN are faked; for the live-tree cases (PatrolLiveLaneLinesTests) so are its tree helpers and
Path.is_dir and Path.resolve, with literal paths and no tree on disk. The lines are the contract's literal strings."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2.lane_lines import lane_lines  # noqa: E402
from codeteam2.team import v1  # noqa: E402

NOW = 1_000_000.0
T = object()
ONE, TWO = Path("/wo/alpha/one"), Path("/wo/alpha/two")
EXISTING = {"/wo/alpha/one", "/wo/alpha/two"}


class LaneLinesTests(unittest.TestCase):
    def lines(self, work, status, pending=None, landing=False, since=NOW - 1800):
        """work: (rows, active, dead, parked, queued) as v1.lane_work gives it; idle_min is 20, the lane quiet 30 min."""
        with patch.object(v1, "lane_work", return_value=work) as lw, \
                patch.object(v1, "landing", return_value=landing), \
                patch.object(v1, "PATROL_DEAD_MIN", 45):
            out = lane_lines(T, "alpha", {"r": 1}, status, {"alpha": {"state_since": since}}, pending or {}, NOW, 20)
        lw.assert_called_once_with(T, "alpha", {"r": 1}, NOW)
        return out

    def test_no_rows_gives_no_lines(self):
        self.assertEqual(self.lines(([], [], ["d1"], 2, ["q1", "q2"]), {}), [])

    def test_an_idle_lane_with_queued_work(self):
        self.assertEqual(self.lines((["row"], [], [], 0, ["q1", "q2", "q3", "q4"]), {"alpha": "idle"}),
                         ["alpha: IDLE WITH WORK, idle 30 min, 4 queued (q1, q2, q3)"])

    def test_an_idle_lane_with_mail_waiting_is_not_named(self):
        self.assertEqual(self.lines((["row"], [], [], 0, ["q1"]), {"alpha": "idle"}, pending={"alpha": 1}), [])

    def test_an_absent_lane_with_queued_work_is_asleep(self):
        self.assertEqual(self.lines((["row"], [], [], 0, ["q1"]), {}),
                         ["alpha: ASLEEP WITH WORK, 1 queued and no mail to wake it"])

    def test_an_absent_lane_with_mail_waiting_is_not_asleep(self):
        self.assertEqual(self.lines((["row"], [], [], 0, ["q1"]), {}, pending={"alpha": 2}), [])

    def test_a_dead_lead(self):
        self.assertEqual(self.lines((["row"], [], ["wo-x"], 0, []), {"alpha": "working"}),
                         ["alpha: DEAD LEAD on wo-x, its worktree untouched 45+ min and nothing running in it"])

    def test_serial_names_four_queued(self):
        self.assertEqual(self.lines((["row"], ["a1"], [], 0, ["q1", "q2", "q3", "q4", "q5"]), {"alpha": "working"}),
                         ["alpha: SERIAL, 1 lead running and 5 queued (q1, q2, q3, q4)"])

    def test_parked_rows_on_a_landing_team(self):
        self.assertEqual(self.lines((["row"], [], [], 2, []), {"alpha": "working"}, landing=True),
                         ['alpha: 2 ledger row(s) past queued with no live lead for a day or more; close or requeue '
                          'them (a row that waits on purpose: stage it "waits for <what>"; a running lead\'s row '
                          'names its tree)'])

    def test_parked_rows_elsewhere(self):
        self.assertEqual(self.lines((["row"], [], [], 1, []), {"alpha": "working"}),
                         ['alpha: 1 ledger row(s) past queued with no live lead for a day or more; close or requeue '
                          'them (a row that waits on purpose: await its feature and stage it "waiting <feature>"; a '
                          'running lead\'s row names its tree)'])

    def test_idle_comes_before_dead_lead(self):
        self.assertEqual(self.lines((["row"], [], ["d1"], 0, []), {"alpha": "done"}),
                         ["alpha: IDLE WITH WORK, idle 30 min, 0 queued ()",
                          "alpha: DEAD LEAD on d1, its worktree untouched 45+ min and nothing running in it"])

    def test_serial_comes_before_parked_rows(self):
        self.assertEqual(self.lines((["row"], [], [], 1, ["q1", "q2"]), {"alpha": "working"}, landing=True),
                         ["alpha: SERIAL, 0 lead running and 2 queued (q1, q2)",
                          'alpha: 1 ledger row(s) past queued with no live lead for a day or more; close or requeue '
                          'them (a row that waits on purpose: stage it "waits for <what>"; a running lead\'s row '
                          'names its tree)'])

    def test_parked_rows_come_before_asleep(self):
        self.assertEqual(self.lines((["row"], [], [], 3, ["q1"]), {}, landing=True),
                         ['alpha: 3 ledger row(s) past queued with no live lead for a day or more; close or requeue '
                          'them (a row that waits on purpose: stage it "waits for <what>"; a running lead\'s row '
                          'names its tree)',
                          "alpha: ASLEEP WITH WORK, 1 queued and no mail to wake it"])


class PatrolLiveLaneLinesTests(unittest.TestCase):
    """Pure: no tree exists on disk. Path.is_dir answers True only for the trees in EXISTING, and Path.resolve only
    normalizes the path's spelling (os.path.normpath)."""
    def patrol(self, trees, active=(), records=None, state="working", activity=NOW - 180):
        rows = [[name, "building", "tree-id,-,"] for name in active]
        rows += [[name, "queued", "-"] for name in ("q1", "q2", "q3")]
        work = (rows, list(active), [], 0, ["q1", "q2", "q3"])
        if records is None:
            records = [{"wo": f"wo-{i}", "zone": "alpha", "tree": str(tree)}
                       for i, tree in enumerate(trees)]
        with patch.object(Path, "is_dir", lambda self: os.path.normpath(self) in EXISTING), \
                patch.object(Path, "resolve", lambda self: Path(os.path.normpath(self))), \
                patch.object(v1, "lane_work", return_value=work), \
                patch.object(v1, "_lead_paths", return_value=trees[:1]), \
                patch.object(v1, "_landing_holds", return_value=False), \
                patch.object(v1, "_someone_inside", return_value=False), \
                patch.object(v1, "_last_activity", return_value=activity), \
                patch.object(v1, "PATROL_DEAD_MIN", 60):
            return lane_lines(T, "alpha", {"r": 1}, {"alpha": state},
                              {"alpha": {"state_since": NOW - 1800}}, {}, NOW, 20, records=records)

    def test_patrollive_two_live_open_trees_suppress_serial(self):
        self.assertEqual(self.patrol([ONE, TWO]), [])

    def test_patrollive_two_quiet_open_trees_still_report_serial(self):
        self.assertEqual(self.patrol([ONE, TWO], activity=NOW - 7200),
                         ["alpha: SERIAL, 0 lead running and 3 queued (q1, q2, q3)"])

    def test_patrollive_queued_work_order_does_not_count(self):
        records = [{"wo": "wo-one", "zone": "alpha", "tree": str(ONE), "queued": True}]
        self.assertEqual(self.patrol([ONE], records=records),
                         ["alpha: SERIAL, 0 lead running and 3 queued (q1, q2, q3)"])

    def test_patrollive_ledger_tree_and_work_order_count_once(self):
        records = [{"wo": "wo-one", "zone": "alpha", "tree": "/wo/alpha/two/../one"}]
        self.assertEqual(self.patrol([ONE], active=["ledger-lead"], records=records),
                         ["alpha: SERIAL, 1 lead running and 3 queued (q1, q2, q3)"])

    def test_patrollive_idle_lane_with_open_tree_is_not_idle_with_work(self):
        self.assertEqual(self.patrol([ONE], state="idle"), [])


if __name__ == "__main__":
    unittest.main()
