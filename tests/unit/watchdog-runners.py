#!/usr/bin/env python3
"""Unit tests for watchdog landing-runner checks."""

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[2] / "bin" / "codeteam-watchdog"
LAND = "com.codeteam.codeteam-land.demo"
RECHECK = "com.codeteam.codeteam-recheck.demo"
VALIDATE = "com.codeteam.codeteam-validate.demo"


def load_watchdog():
    loader = importlib.machinery.SourceFileLoader("watchdog_under_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    output = io.StringIO()
    with (patch("sys.dont_write_bytecode", True),
          patch("subprocess.run", side_effect=AssertionError("subprocess during import")),
          patch("subprocess.Popen", side_effect=AssertionError("process during import")),
          patch("pathlib.Path.read_text", side_effect=AssertionError("state read during import")),
          patch("pathlib.Path.write_text", side_effect=AssertionError("state write during import")),
          patch("pathlib.Path.mkdir", side_effect=AssertionError("mkdir during import")),
          contextlib.redirect_stdout(output), contextlib.redirect_stderr(output)):
        loader.exec_module(module)
    return module, output.getvalue()


class FakeRun:
    def __init__(self, answers=None):
        self.calls = []
        self.answers = answers or {}

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        label = argv[-1].rsplit("/", 1)[-1]
        rc, stdout = self.answers.get(label, (0, "state = running"))
        return SimpleNamespace(returncode=rc, stdout=stdout)


class RunnerProblemsTests(unittest.TestCase):
    def setUp(self):
        self.watchdog, _ = load_watchdog()

    def test_import_has_no_side_effects(self):
        _, output = load_watchdog()
        self.assertEqual(output, "")

    def test_queries_all_three_labels_in_order(self):
        run = FakeRun()
        self.watchdog.runner_problems("demo", run=run, uid=1234)
        self.assertEqual(run.calls, [
            ["launchctl", "print", "gui/1234/com.codeteam.codeteam-land.demo"],
            ["launchctl", "print", "gui/1234/com.codeteam.codeteam-recheck.demo"],
            ["launchctl", "print", "gui/1234/com.codeteam.codeteam-validate.demo"],
        ])

    def test_all_running_has_no_problems(self):
        self.assertEqual(self.watchdog.runner_problems("demo", run=FakeRun(), uid=1234), [])

    def test_waiting_recheck_is_the_only_problem(self):
        run = FakeRun({RECHECK: (0, "state = waiting")})
        self.assertEqual(self.watchdog.runner_problems("demo", run=run, uid=1234),
                         ["recheck runner not running"])

    def test_failed_validation_print_is_a_problem_even_if_stdout_says_running(self):
        run = FakeRun({VALIDATE: (1, "state = running")})
        self.assertEqual(self.watchdog.runner_problems("demo", run=run, uid=1234),
                         ["validation runner not running"])

    def test_all_down_problems_are_ordered_and_have_distinct_episode_keys(self):
        run = FakeRun({LAND: (0, "state = waiting"), RECHECK: (0, "state = waiting"),
                       VALIDATE: (0, "state = waiting")})
        problems = self.watchdog.runner_problems("demo", run=run, uid=1234)
        self.assertEqual(problems, ["landing queue runner not running", "recheck runner not running",
                                    "validation runner not running"])
        self.assertEqual([" ".join(problem.split()[:2]) for problem in problems],
                         ["landing queue", "recheck runner", "validation runner"])

    def test_check_reports_all_runner_problems_for_land_enabled_team(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            teams = root / "teams"
            teams.mkdir()
            team = root / "scratch-team"
            v2 = team / "team" / "v2"
            v2.mkdir(parents=True)
            (v2 / "up").touch()
            (v2 / "heartbeat").touch()
            (teams / "demo.toml").write_text(f'worktree_root = "{team}"\n[land]\nenabled = true\n')
            state = root / "state.json"
            problems = ["landing queue runner not running", "recheck runner not running",
                        "validation runner not running"]
            with (patch.object(self.watchdog, "TEAMS", teams), patch.object(self.watchdog, "STATE", state),
                  patch.object(self.watchdog, "WORKSPACE", root),
                  patch.object(self.watchdog.time, "time", return_value=(v2 / "heartbeat").stat().st_mtime),
                  patch.object(self.watchdog, "runner_problems", return_value=problems, create=True),
                  patch.object(self.watchdog.subprocess, "run", return_value=SimpleNamespace(returncode=0,
                                                                                             stdout="state = running")),
                  patch.object(self.watchdog, "notify") as notify, patch.object(self.watchdog, "sweep_queue"),
                  patch.object(self.watchdog, "sweep_disk"), contextlib.redirect_stdout(io.StringIO())):
                self.watchdog.check()
            self.assertEqual([call.args[1] for call in notify.call_args_list], problems)
            self.assertEqual(set(json.loads(state.read_text())),
                             {"demo: landing queue", "demo: recheck runner", "demo: validation runner"})


class FullDiskTests(unittest.TestCase):
    """On a full disk the state file cannot be written, and the pass once stopped there, before the
    disk floor ran; build folders idle since 08:52 were cleared only at 09:39."""

    def test_a_state_write_that_fails_on_a_full_disk_still_lets_the_floor_and_the_queue_sweep_run(self):
        watchdog, _ = load_watchdog()
        ran = []

        class FullState:
            def __init__(self, folder):
                self.parent = folder

            def read_text(self):
                raise FileNotFoundError(2, "No such file or directory")

            def write_text(self, text):
                raise OSError(28, "No space left on device")

        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with (patch.object(watchdog, "TEAMS", Path(tmp)), patch.object(watchdog, "STATE", FullState(Path(tmp))),
                  patch.object(watchdog, "WORKSPACE", Path(tmp)),
                  patch.object(watchdog, "sweep_queue", side_effect=lambda: ran.append("queue")),
                  patch.object(watchdog, "sweep_disk", side_effect=lambda: ran.append("disk")),
                  contextlib.redirect_stdout(out)):
                watchdog.check()
        self.assertEqual(ran, ["queue", "disk"])
        self.assertIn("failed: OSError: [Errno 28] No space left on device", out.getvalue())

    def test_a_failing_floor_does_not_stop_the_team_checks(self):
        watchdog, _ = load_watchdog()
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            out = io.StringIO()
            with (patch.object(watchdog, "TEAMS", Path(tmp)), patch.object(watchdog, "STATE", state),
                  patch.object(watchdog, "WORKSPACE", Path(tmp)),
                  patch.object(watchdog, "sweep_queue"),
                  patch.object(watchdog, "sweep_disk", side_effect=OSError(28, "No space left on device")),
                  contextlib.redirect_stdout(out)):
                watchdog.check()
            self.assertEqual(json.loads(state.read_text()), {})
        self.assertIn("sweep_disk failed: OSError: [Errno 28] No space left on device", out.getvalue())


class LandCloneFloorTests(unittest.TestCase):
    """The landing tool's own clones (one team's land/validate/target held 50 GiB, land/itest/target
    23 GiB) are swept below the 50 GiB red line when no Stage 5 or 6 run holds them; a team's manifest that
    lives in its own clone is checked too."""

    def setUp(self):
        self.watchdog, _ = load_watchdog()

    def test_manifests_adds_an_up_team_whose_manifest_lives_in_its_own_clone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            teams, workspace = root / "teams", root / "workspace"
            teams.mkdir()
            (teams / "a.toml").write_text("")
            for name in ("a", "gizmos"):
                (workspace / f"team-{name}" / "team" / "v2").mkdir(parents=True)
                (workspace / f"team-{name}" / "team" / "v2" / "up").touch()
            own = workspace / "team-gizmos" / "design" / "gizmos" / "teams"
            own.mkdir(parents=True)
            for name in ("gadgets", "gizmos"):     # gizmos' clone holds every team's manifest
                (own / f"{name}.toml").write_text("")
            (workspace / "team-down" / "design" / "down" / "teams").mkdir(parents=True)
            (workspace / "team-down" / "design" / "down" / "teams" / "down.toml").write_text("")
            self.assertEqual(self.watchdog.manifests(teams, workspace), [teams / "a.toml", own / "gizmos.toml"])

    def test_land_clones_follow_the_validation_tier(self):
        root = Path("/t")
        clones = self.watchdog.land_clones
        self.assertEqual(clones({}, root), {})
        self.assertEqual(clones({"land": {"enabled": True}}, root),
                         {"itest": root / "land" / "itest", "validate": root / "land" / "validate"})
        self.assertEqual(clones({"land": {"remote": {"host": "remote-box", "path": "~/x"}}}, root),
                         {"itest": root / "land" / "itest"})
        self.assertEqual(clones({"land": {"validate": {"local": True, "path": "/v"}}}, root),
                         {"itest": root / "land" / "itest", "validate": Path("/v")})
        self.assertEqual(clones({"land": {"validate": {"host": "box", "path": "/v"}}}, root),
                         {"itest": root / "land" / "itest"})

    def test_busy_land_clones_are_the_live_stage_5_and_6_runs_by_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            stages = Path(tmp)
            rows = {"1": {"stage": "Stage 6", "name": "validation at abc", "pid": 111},
                    "2": {"stage": "Stage 5", "name": "recheck of w at M 1", "pid": 222},     # dead
                    "3": {"stage": "Stage 2", "name": "check of w", "pid": 333},              # not a clone of its own
                    "4": {"stage": "Stage 5", "name": "recheck of v at M 2", "pid": 444}}     # command unreadable
            for name, row in rows.items():
                (stages / f"{name}.json").write_text(json.dumps(row))
            (stages / "5.json").write_text("{")
            commands = {111: "python3 /x/codeteam-land /m/teams/t.toml validate-run\n", 444: None}
            with patch.object(self.watchdog, "alive", side_effect=lambda pid: pid != 222):
                busy = self.watchdog.busy_land_clones(stages, command=commands.get)
            self.assertEqual(busy, {(os.path.realpath("/m/teams/t.toml"), "validate"), ("*", "itest")})

    def test_an_idle_land_clone_loses_its_build_output_only_below_the_red_line_and_never_while_held(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            teams, q, root = base / "teams", base / "queue", base / "team-t"
            teams.mkdir()
            q.mkdir()
            manifest = teams / "t.toml"
            manifest.write_text(f'worktree_root = "{root}"\n[land]\nenabled = true\n')
            for kind in ("itest", "validate"):
                (root / "land" / kind / "target" / "debug").mkdir(parents=True)
            stages = base / "restart" / "stages"
            stages.mkdir(parents=True)
            (stages / "9-0.json").write_text(json.dumps({"stage": "Stage 6", "name": "validation at abc", "pid": 9}))
            ran = {9: f"python3 codeteam-land {manifest} validate-run"}
            with (patch.object(self.watchdog, "last_active", return_value=0.0),
                  patch.object(self.watchdog, "alive", side_effect=lambda pid: pid in ran),
                  patch.object(self.watchdog, "command_of", side_effect=ran.get),
                  patch.object(self.watchdog.subprocess, "Popen"), patch.object(self.watchdog, "notify"),
                  contextlib.redirect_stdout(io.StringIO())):
                above = self.watchdog.sweep_disk(teams, q, min_gb=150, idle_s=1800, free=lambda: 100.0,
                                                 land_min_gb=53.7, workspace=base / "none")
                self.assertEqual(above, [])
                self.assertTrue((root / "land" / "itest" / "target").is_dir())
                below = self.watchdog.sweep_disk(teams, q, min_gb=150, idle_s=1800, free=lambda: 20.0,
                                                 land_min_gb=53.7, workspace=base / "none")
            self.assertEqual(len(below), 1, below)
            self.assertIn(str(root / "land" / "itest" / "target"), below[0])
            self.assertFalse((root / "land" / "itest" / "target").exists())
            self.assertTrue((root / "land" / "validate" / "target").is_dir(), "Stage 6 holds the validate clone")
            self.assertTrue((root / "land" / "itest" / ".." / "itest").is_dir(), "the clone itself stays")


if __name__ == "__main__":
    unittest.main()
