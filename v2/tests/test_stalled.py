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

    def tree(self, name, zone="eventlog", commits=1, age_min=120, queued=False, dirty=False, held=False):
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
        if held:
            rec["held"] = {"because": "kept on its branch until the owner decides", "at": "2026-11-12T01:20:00-06:00"}
        (self.land / "wo" / f"{name}.json").write_text(json.dumps(rec))

    def lines(self, status=None, st=None, pending=None, landing=frozenset()):
        return patrol.stalled_work_orders(self.land, status or {}, st or {}, pending or {}, self.now, landing=landing)

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
        self.tree("ruled", zone="e", held=True)             # held on purpose by a ruling
        self.assertEqual(self.lines(status={"c": "working"}, pending={"d": 1}), [])

    # integration: tree() runs real git processes
    @integration_only
    def test_idle_coordinator_counts_after_twenty_minutes(self):
        self.tree("rework")
        self.assertEqual(self.lines(status={"eventlog": "idle"}, st={"eventlog": {"state_since": self.now - 300}}), [])
        self.assertEqual(len(self.lines(status={"eventlog": "idle"}, st={"eventlog": {"state_since": self.now - 3600}})), 1)

    # integration: tree() runs real git processes
    @integration_only
    def test_a_work_order_whose_land_is_running_is_not_stalled(self):
        """Stage 2 changes nothing in the tree for its whole run (70 min for one lane's land
        once), so a work order a live land names is not stalled, and is judged as before once the land ends."""
        self.tree("landing")
        self.assertEqual(self.lines(landing={"landing", "other"}), [])
        self.assertEqual(len(self.lines(landing={"other"})), 1)

    def bounce(self, name, minutes_ago):
        p = self.land / "wo" / f"{name}.bounce.txt"
        p.write_text("AGENTS.md\n")
        at = self.now - minutes_ago * 60
        os.utime(p, (at, at))

    def promote(self, minutes_ago):
        import datetime as dt
        at = dt.datetime.fromtimestamp(self.now - minutes_ago * 60).astimezone().isoformat(timespec="seconds")
        with open(self.land / "landed.log", "a") as f:
            f.write(json.dumps({"time": at, "wos": ["other"], "hash": "a" * 40}) + "\n")
            f.write(json.dumps({"time": at, "promote": "b" * 40, "to": "main"}) + "\n")

    # integration: tree() runs real git processes
    @integration_only
    def test_a_bounced_work_order_waits_for_the_next_promote(self):
        """A work order sent back by a landing conflict waits, as the landing tool told it, for
        the landed work to be promoted; once a promote is recorded after the bounce it is judged again."""
        self.tree("conflicted")                             # last commit 120 min ago
        self.bounce("conflicted", 60)                       # sent back 60 min ago, nothing done since
        self.assertEqual(self.lines(), [])                  # no promote recorded at all
        self.promote(180)                                   # a promote before the bounce changes nothing
        self.assertEqual(self.lines(), [])
        self.promote(30)                                    # promoted after the bounce: the lane must act now
        out = self.lines()
        self.assertEqual(len(out), 1)
        self.assertIn("STALLED WORK ORDER conflicted", out[0])

    # integration: tree() runs real git processes
    @integration_only
    def test_work_after_a_bounce_is_judged_as_before(self):
        self.tree("resolved")                               # committed 120 min ago, after the bounce
        self.bounce("resolved", 180)
        self.assertEqual(len(self.lines()), 1)

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


ACME = "/home/u/codeteam/teams/acme.toml"
PY = "/opt/homebrew/Cellar/python@3.15/3.15.0_1/Frameworks/Python.framework/Versions/3.15/Resources/Python.app/Contents/MacOS/Python"
LAND = "/home/u/codeteam/bin/codeteam-land"


class LandingWorkOrdersTest(unittest.TestCase):
    """Which work orders a live `codeteam-land <manifest> land` names, read from a process listing."""

    def names(self, *lines, manifest=ACME):
        return patrol.landing_work_orders("\n".join(lines) + "\n", manifest)

    def test_a_lone_land_and_every_member_of_a_set(self):
        self.assertEqual(self.names(f"{PY} {LAND} {ACME} land agent-a1"), {"agent-a1"})
        self.assertEqual(self.names(f"{PY} {LAND} {ACME} land agent-a1 --with agent-a2 --with=agent-a3 --fixes agent-a9#1"),
                         {"agent-a1", "agent-a2", "agent-a3", "agent-a9#1"})
        self.assertEqual(self.names(f"{LAND} {ACME} land agent-a1"), {"agent-a1"})

    def test_another_team_another_command_or_no_land_names_nothing(self):
        self.assertEqual(self.names(f"{PY} {LAND} /home/u/codeteam/teams/widgets.toml land agent-a1"), set())
        self.assertEqual(self.names(f"{PY} {LAND} {ACME} queue-run", f"{PY} {LAND} {ACME} land-hold agent-a1"), set())
        self.assertEqual(self.names(f"{PY} /home/u/codeteam/bin/zone-tool job submit --key agent-a1"), set())

    def test_a_command_line_that_only_mentions_a_land_names_nothing(self):
        # A shell wrapper or a session whose prompt quotes the command is not the land itself.
        self.assertEqual(self.names(f"/bin/zsh -c source x.sh && {LAND} {ACME} land agent-a1",
                                    f"/home/u/.local/bin/claude --agent zone-coordinator run {LAND} {ACME} land agent-a2"),
                         set())

    def test_an_empty_listing_names_nothing(self):
        self.assertEqual(patrol.landing_work_orders("", ACME), set())


if __name__ == "__main__":
    unittest.main()
