"""Patrol sees a v5 work order that has stopped, and wakes the orchestrator for it."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import integration_only  # noqa: E402
from codeteam2 import patrol, scheduler  # noqa: E402

G = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]


class StalledTest(unittest.TestCase):
    def setUp(self):
        self.w = Path(tempfile.mkdtemp())
        self.land = self.w / "land"
        (self.land / "wo").mkdir(parents=True)
        self.now = time.time()

    def tree(self, name, zone="eventlog", commits=1, age_min=120, queued=False, dirty=False):
        tr = self.w / "wo" / zone / name
        tr.mkdir(parents=True)
        when = int(self.now - age_min * 60)
        env = dict(os.environ, GIT_COMMITTER_DATE=f"@{when}", GIT_AUTHOR_DATE=f"@{when}")
        subprocess.run([*G, "init", "-q"], cwd=tr)
        subprocess.run([*G, "commit", "-q", "--allow-empty", "-m", "base"], cwd=tr, env=env)
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tr, capture_output=True, text=True).stdout.strip()
        for i in range(commits):
            subprocess.run([*G, "commit", "-q", "--allow-empty", "-m", f"work {i}"], cwd=tr, env=env)
        if dirty:
            (tr / "edit.txt").write_text("x")
        rec = {"wo": name, "zone": zone, "tree": str(tr), "base": base}
        if queued:
            rec["queued"] = "2026-11-09T07:00:00-06:00"
        (self.land / "wo" / f"{name}.json").write_text(json.dumps(rec))

    def lines(self, status=None, st=None, pending=None):
        return patrol.stalled_work_orders(self.land, status or {}, st or {}, pending or {}, self.now)

    # integration: tree() runs real git processes
    @integration_only
    def test_work_untouched_with_coordinator_asleep_is_flagged(self):
        self.tree("rework")
        out = self.lines()
        self.assertEqual(len(out), 1)
        self.assertIn("eventlog: STALLED WORK ORDER rework", out[0])
        self.assertIn("asleep", out[0])

    # integration: tree() runs real git processes
    @integration_only
    def test_a_commit_with_uncommitted_edits_counts(self):
        self.tree("edits", commits=1, dirty=True)
        self.assertEqual(len(self.lines()), 1)

    # integration: tree() runs real git processes
    @integration_only
    def test_not_flagged(self):
        self.tree("empty", commits=0)                       # held on purpose, or a cancelled start
        self.tree("fresh", zone="a", age_min=10)            # changed ten minutes ago
        self.tree("queued", zone="b", queued=True)          # waiting to land
        self.tree("busy", zone="c")                         # its coordinator is working
        self.tree("mail", zone="d")                         # mail is waiting for its coordinator
        self.assertEqual(self.lines(status={"c": "working"}, pending={"d": 1}), [])

    # integration: tree() runs real git processes
    @integration_only
    def test_idle_coordinator_counts_after_twenty_minutes(self):
        self.tree("rework")
        self.assertEqual(self.lines(status={"eventlog": "idle"}, st={"eventlog": {"state_since": self.now - 300}}), [])
        self.assertEqual(len(self.lines(status={"eventlog": "idle"}, st={"eventlog": {"state_since": self.now - 3600}})), 1)

    # integration: tree() runs real git processes
    @integration_only
    def test_line_is_the_same_each_time(self):
        self.tree("rework")
        a = self.lines()
        self.now += 1800
        self.assertEqual(a, self.lines())

    def test_stopped_work_wakes_the_orchestrator_and_the_rest_rides_along(self):
        sent = []
        rt = object.__new__(scheduler.Runtime)
        rt.team = SimpleNamespace(patrol_min=30, dir=self.w, product="gizmos", t=SimpleNamespace(orc_name=lambda: "Orc-Gizmos"))
        rt.store = SimpleNamespace(add=lambda *a, **k: sent.append((a[5], k.get("ride", False))))
        rt.log = lambda *a: None
        rt.herdr = SimpleNamespace(notify=lambda *a: None)
        real = scheduler.patrol_mod.findings
        scheduler.patrol_mod.findings = lambda *a: ["eventlog: STALLED WORK ORDER rework, ...", "BRANCHES: 1 here"]
        try:
            rt.patrol({}, {}, self.now)
        finally:
            scheduler.patrol_mod.findings = real
        self.assertEqual(len(sent), 2)
        woke = [t for t, ride in sent if not ride]
        self.assertEqual(len(woke), 1)
        self.assertIn("STALLED WORK ORDER", woke[0])
        self.assertTrue(any(ride and "BRANCHES" in t for t, ride in sent))


if __name__ == "__main__":
    unittest.main()
