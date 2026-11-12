#!/usr/bin/env python3
"""Unit tests for watchdog landing-runner checks."""

import contextlib
import importlib.machinery
import importlib.util
import io
import json
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


if __name__ == "__main__":
    unittest.main()
