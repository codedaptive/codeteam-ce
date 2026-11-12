#!/usr/bin/env python3
"""Unit tests for the watchdog's launchd reinstall."""

import contextlib
import importlib.machinery
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[2] / "bin" / "codeteam-watchdog"
LABEL = "com.codeteam.codeteam-watchdog"
ERROR = "Bootstrap failed: 5: Input/output error"


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
    return module


class FakeLaunchctl:
    def __init__(self, prints=(), bootstraps=(), default_print=113):
        self.prints = iter(prints)
        self.bootstraps = iter(bootstraps)
        self.default_print = default_print
        self.calls = []
        self.sleeps = []

    def run(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if argv[1] == "bootout":
            return SimpleNamespace(returncode=1, stderr="not loaded", stdout="")
        if argv[1] == "print":
            # An unbounded poll fails here instead of hanging the test.
            assert sum(c[0][1] == "print" for c in self.calls) <= 300, "print polling did not stop at the bound"
            return SimpleNamespace(returncode=next(self.prints, self.default_print), stderr="", stdout="")
        if argv[1] == "bootstrap":
            rc, stderr = next(self.bootstraps, (0, ""))
            return SimpleNamespace(returncode=rc, stderr=stderr, stdout="")
        raise AssertionError(f"unexpected command: {argv}")

    def sleep(self, seconds):
        self.sleeps.append(seconds)


class WatchdogInstallTests(unittest.TestCase):
    def setUp(self):
        self.watchdog = load_watchdog()
        self.plist = Path("/tmp/watchdog-test.plist")

    def test_imports_launchd_from_own_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            share = Path(tmp) / "share"
            share.mkdir()
            (share / "codeteam_launchd.py").write_text("DECOY = True\n")
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                with (patch.dict(sys.modules), patch.object(sys, "path", list(sys.path)),
                      patch.object(sys, "path_importer_cache", {})):
                    sys.modules.pop("codeteam_launchd", None)
                    module = load_watchdog()
                    self.assertEqual(
                        Path(module.codeteam_launchd.__file__).resolve(),
                        SCRIPT.parents[1] / "share" / "codeteam_launchd.py",
                    )
                    self.assertFalse(hasattr(module.codeteam_launchd, "DECOY"))
            finally:
                os.chdir(cwd)

    def test_reinstall_forwards_arguments_and_returns_reason(self):
        fake = FakeLaunchctl()
        run, sleep = fake.run, fake.sleep
        result = self.watchdog.codeteam_launchd.ReinstallResult(False, "distinctive failure")
        with patch.object(self.watchdog.codeteam_launchd, "reinstall", return_value=result) as reinstall:
            reason = self.watchdog.launchd_reinstall(
                LABEL, self.plist, 1234, run=run, sleep=sleep,
                wait_s=3.0, poll_s=0.5, retry_s=1.5,
            )
        self.assertEqual(reason, "distinctive failure")
        reinstall.assert_called_once_with(
            LABEL, self.plist, 1234, run=run, sleep=sleep,
            wait_s=3.0, poll_s=0.5, retry_s=1.5,
        )

    def test_waits_for_unload_before_bootstrap(self):
        fake = FakeLaunchctl(prints=[0, 0, 113])
        result = self.watchdog.launchd_reinstall(LABEL, self.plist, 1234, run=fake.run, sleep=fake.sleep)
        self.assertIsNone(result)
        self.assertEqual([argv for argv, _ in fake.calls], [
            ["launchctl", "bootout", "gui/1234/com.codeteam.codeteam-watchdog"],
            ["launchctl", "print", "gui/1234/com.codeteam.codeteam-watchdog"],
            ["launchctl", "print", "gui/1234/com.codeteam.codeteam-watchdog"],
            ["launchctl", "print", "gui/1234/com.codeteam.codeteam-watchdog"],
            ["launchctl", "bootstrap", "gui/1234", "/tmp/watchdog-test.plist"],
        ])
        self.assertEqual(fake.calls[-1][1], {"capture_output": True, "text": True})
        self.assertEqual(fake.sleeps, [0.2, 0.2])

    def test_bootstrap_failure_is_retried_once(self):
        fake = FakeLaunchctl(bootstraps=[(5, ERROR), (0, "")])
        result = self.watchdog.launchd_reinstall(LABEL, self.plist, 1234, run=fake.run, sleep=fake.sleep)
        self.assertIsNone(result)
        self.assertEqual([argv for argv, _ in fake.calls], [
            ["launchctl", "bootout", "gui/1234/com.codeteam.codeteam-watchdog"],
            ["launchctl", "print", "gui/1234/com.codeteam.codeteam-watchdog"],
            ["launchctl", "bootstrap", "gui/1234", "/tmp/watchdog-test.plist"],
            ["launchctl", "bootstrap", "gui/1234", "/tmp/watchdog-test.plist"],
        ])
        self.assertEqual(fake.sleeps, [2.0])

    def test_already_unloaded_needs_no_sleep(self):
        fake = FakeLaunchctl(prints=[113])
        result = self.watchdog.launchd_reinstall(LABEL, self.plist, 1234, run=fake.run, sleep=fake.sleep)
        self.assertIsNone(result)
        self.assertEqual([argv[1] for argv, _ in fake.calls], ["bootout", "print", "bootstrap"])
        self.assertEqual(fake.sleeps, [])

    def test_still_loaded_at_bound_returns_error_without_bootstrap(self):
        fake = FakeLaunchctl(default_print=0)
        result = self.watchdog.launchd_reinstall(
            LABEL, self.plist, 1234, run=fake.run, sleep=fake.sleep, wait_s=0.6, poll_s=0.2)
        self.assertIsInstance(result, str)
        self.assertIn("still loaded", result)
        self.assertEqual(fake.calls[0][0], ["launchctl", "bootout", "gui/1234/com.codeteam.codeteam-watchdog"])
        self.assertGreaterEqual(len(fake.calls), 2)
        self.assertLessEqual(len(fake.calls), 5)
        self.assertTrue(all(argv[1] == "print" for argv, _ in fake.calls[1:]))

    def test_install_reports_persistent_bootstrap_failure_and_exits_nonzero(self):
        fake = FakeLaunchctl(bootstraps=[(5, ERROR), (5, ERROR)])
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "Library" / "LaunchAgents").mkdir(parents=True)
            with (patch.object(Path, "home", return_value=home),
                  patch.object(self.watchdog.os, "getuid", return_value=1234),
                  patch.object(self.watchdog.subprocess, "run", side_effect=fake.run),
                  patch.object(self.watchdog.time, "sleep", side_effect=fake.sleep),
                  contextlib.redirect_stdout(output), contextlib.redirect_stderr(output)):
                with self.assertRaises(SystemExit) as raised:
                    self.watchdog.install()
            self.assertNotIn(raised.exception.code, (None, 0))
            self.assertIn("com.codeteam.codeteam-watchdog", output.getvalue())
            self.assertIn("Bootstrap failed: 5: Input/output error", output.getvalue())
            self.assertEqual([argv[1] for argv, _ in fake.calls], ["bootout", "print", "bootstrap", "bootstrap"])
            self.assertTrue((home / "Library" / "LaunchAgents" / "com.codeteam.codeteam-watchdog.plist").is_file())

    def test_install_still_loaded_exits_nonzero_without_bootstrap(self):
        fake = FakeLaunchctl(default_print=0)
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "Library" / "LaunchAgents").mkdir(parents=True)
            with (patch.object(Path, "home", return_value=home),
                  patch.object(self.watchdog.os, "getuid", return_value=1234),
                  patch.object(self.watchdog.subprocess, "run", side_effect=fake.run),
                  patch.object(self.watchdog.time, "sleep", side_effect=fake.sleep),
                  contextlib.redirect_stdout(output), contextlib.redirect_stderr(output)):
                with self.assertRaises(SystemExit) as raised:
                    self.watchdog.install()
            self.assertNotIn(raised.exception.code, (None, 0))
            self.assertIn("com.codeteam.codeteam-watchdog", output.getvalue())
            self.assertIn("still loaded", output.getvalue())
            self.assertNotIn("bootstrap", [argv[1] for argv, _ in fake.calls])

    def test_install_success_prints_label_after_unload(self):
        fake = FakeLaunchctl(prints=[113])
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "Library" / "LaunchAgents").mkdir(parents=True)
            with (patch.object(Path, "home", return_value=home),
                  patch.object(self.watchdog.os, "getuid", return_value=1234),
                  patch.object(self.watchdog.subprocess, "run", side_effect=fake.run),
                  patch.object(self.watchdog.time, "sleep", side_effect=fake.sleep),
                  contextlib.redirect_stdout(output), contextlib.redirect_stderr(output)):
                self.watchdog.install()
            self.assertIn("installed com.codeteam.codeteam-watchdog", output.getvalue())
            self.assertEqual([argv[1] for argv, _ in fake.calls], ["bootout", "print", "bootstrap"])
            self.assertTrue((home / "Library" / "LaunchAgents" / "com.codeteam.codeteam-watchdog.plist").is_file())


if __name__ == "__main__":
    unittest.main()
