#!/usr/bin/env python3
"""Unit tests for the landing runner checks and import safety."""

import contextlib
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[2] / "bin" / "codeteam-check-team"


def load_checker():
    loader = importlib.machinery.SourceFileLoader("check_team_under_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    output = io.StringIO()
    with (patch("pathlib.Path.home", return_value=Path("/nonexistent-check-team-test-home")),
          patch("pathlib.Path.exists", return_value=False),
          patch("sys.argv", ["check-team", "x"]),
          patch("sys.dont_write_bytecode", True),
          patch("sys.exit") as exit_mock,
          patch("subprocess.run", side_effect=AssertionError("subprocess during import")),
          contextlib.redirect_stdout(output)):
        loader.exec_module(module)
    return module, output.getvalue(), exit_mock.call_args_list


class RunnerChecksTests(unittest.TestCase):
    def test_land_only_running_checks_both_labels_in_order(self):
        module, _, _ = load_checker()
        labels = []

        def running(label):
            labels.append(label)
            return "codeteam-land" in label

        self.assertEqual(module.runner_checks("x", running), [
            (True, "v5: queue-run runs (launchd)", "codeteam-land <m> service install"),
            (False, "v5: recheck-run runs (launchd)", "codeteam-land <m> service install"),
            (False, "v5: validate-run runs (launchd)", "codeteam-land <m> service install"),
        ])
        self.assertEqual(labels, ["com.codeteam.codeteam-land.x", "com.codeteam.codeteam-recheck.x", "com.codeteam.codeteam-validate.x"])

    def test_both_runners_running(self):
        module, _, _ = load_checker()
        self.assertEqual(module.runner_checks("x", lambda label: True), [
            (True, "v5: queue-run runs (launchd)", "codeteam-land <m> service install"),
            (True, "v5: recheck-run runs (launchd)", "codeteam-land <m> service install"),
            (True, "v5: validate-run runs (launchd)", "codeteam-land <m> service install"),
        ])

    def test_neither_runner_running(self):
        module, _, _ = load_checker()
        self.assertEqual(module.runner_checks("x", lambda label: False), [
            (False, "v5: queue-run runs (launchd)", "codeteam-land <m> service install"),
            (False, "v5: recheck-run runs (launchd)", "codeteam-land <m> service install"),
            (False, "v5: validate-run runs (launchd)", "codeteam-land <m> service install"),
        ])

    def test_import_does_not_run_team_checks_or_exit(self):
        _, output, exits = load_checker()
        self.assertEqual(output, "")
        self.assertEqual(exits, [])


if __name__ == "__main__":
    unittest.main()
