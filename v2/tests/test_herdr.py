"""Tests for launching the herdr server without contacting launchd or herdr."""
import fcntl
import os
import plistlib
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import call, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import integration_only  # noqa: E402
from codeteam2 import herdr  # noqa: E402


class FakeCommands:
    def __init__(self, statuses=(), print_stdout="", loaded_after_bootout=0, bootstrap_returncodes=(),
                 bootstrap_stderr=None):
        self.bootstrap_stderr = bootstrap_stderr
        self.statuses = deque(statuses)
        self.print_stdout = print_stdout
        self.loaded_after_bootout = loaded_after_bootout
        self.remaining_loaded = None
        self.booted_out = False
        self.bootstrap_returncodes = deque(bootstrap_returncodes)
        self.bootstrap_attempts = 0
        self.calls = []
        self.print_kwargs = []
        self.events = []
        self.status_called = threading.Event()
        self.running = threading.Event()

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        self.events.append(list(argv))
        if argv == [herdr.HERDR_BIN, "status", "server"]:
            self.status_called.set()
            running = self.statuses.popleft() if self.statuses else self.running.is_set()
            return subprocess.CompletedProcess(argv, 0, "status: running" if running else "status: stopped", "")
        if argv[:2] == ["launchctl", "print"]:
            self.print_kwargs.append(kwargs)
            if self.booted_out and self.remaining_loaded == 0:
                return subprocess.CompletedProcess(argv, 113, "", "Could not find service")
            if self.booted_out and self.remaining_loaded is not None:
                self.remaining_loaded -= 1
            return subprocess.CompletedProcess(argv, 0, self.print_stdout, "")
        if argv[:2] == ["launchctl", "bootout"]:
            self.booted_out = True
            self.remaining_loaded = self.loaded_after_bootout
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[:2] == ["launchctl", "bootstrap"]:
            self.bootstrap_attempts += 1
            rc = self.bootstrap_returncodes.popleft() if self.bootstrap_returncodes else 0
            if rc == 0:
                self.booted_out = False
            stderr = self.bootstrap_stderr
            if stderr is None:
                stderr = f" bootstrap failure {self.bootstrap_attempts} \n"
            return subprocess.CompletedProcess(argv, rc, "", stderr)
        raise AssertionError(f"unexpected subprocess: {argv!r}")

    @property
    def launchctl_calls(self):
        return [argv for argv in self.calls if argv[0] == "launchctl"]


class TestHerdrLaunchd(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.launchd_dir = Path(self.temp.name) / "nested" / "launchd"
        self.label = "com.codeteam.codeteam2.herdr.a_5fb"
        self.target = f"gui/{os.getuid()}/{self.label}"
        self.plist = self.launchd_dir / f"{self.label}.plist"
        self.commands = FakeCommands()
        self.addCleanup(patch.stopall)
        patch.object(herdr, "LAUNCHD_DIR", self.launchd_dir, create=True).start()
        patch.object(herdr.subprocess, "run", side_effect=self.commands).start()
        patch.object(herdr.subprocess, "Popen", side_effect=AssertionError("Popen must not be called")).start()
        self.sleep = patch.object(herdr.time, "sleep").start()
        self.sleep.side_effect = lambda seconds: self.commands.events.append(call(seconds))
        patch.dict(os.environ, {"HERDR_SOCKET_PATH": "/tmp/must-not-leak"}).start()
        self.client = herdr.Herdr("a_b")

    def assert_launch(self, logfile):
        self.commands.statuses.extend([False, False, True])
        self.assertTrue(self.client.ensure_server(logfile=logfile))
        self.assertEqual(self.commands.launchctl_calls, [
            ["launchctl", "print", self.target],
            ["launchctl", "bootout", self.target],
            ["launchctl", "print", self.target],
            ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(self.plist)],
        ])
        with self.plist.open("rb") as stream:
            config = plistlib.load(stream)
        self.assertEqual(config["Label"], self.label)
        self.assertEqual(config["ProgramArguments"], [herdr.HERDR_BIN, "server", "--session", "a_b"])
        env = config["EnvironmentVariables"]
        self.assertEqual(env["HERDR_SESSION"], "a_b")
        self.assertNotIn("HERDR_SOCKET_PATH", env)
        self.assertTrue(env["PATH"].startswith(f"/opt/homebrew/bin:{os.path.expanduser('~/.local/bin')}:"))
        self.assertEqual(config["StandardInPath"], "/dev/null")
        self.assertEqual(config["StandardOutPath"], logfile or "/dev/null")
        self.assertEqual(config["StandardErrorPath"], logfile or "/dev/null")
        self.assertEqual(config["WorkingDirectory"], str(Path.home()))
        self.assertIs(config["RunAtLoad"], True)
        self.assertEqual(config["ProcessType"], "Interactive")     # never launchd's default class (2026-11-09)
        self.assertNotIn("KeepAlive", config)
        self.sleep.assert_called_once_with(0.2)

    def test_launch_with_logfile(self):
        self.assert_launch(str(Path(self.temp.name) / "herdr.log"))

    def test_launch_without_logfile(self):
        self.assert_launch(None)

    def test_plist_permissions_ignore_umask(self):
        self.commands.statuses.extend([False, False, True])
        previous_umask = os.umask(0o022)
        try:
            self.assertTrue(self.client.ensure_server())
        finally:
            os.umask(previous_umask)
        self.assertEqual(stat.S_IMODE(self.plist.stat().st_mode), 0o600)

    def test_existing_launchd_directory_is_private(self):
        self.launchd_dir.mkdir(parents=True, mode=0o755)
        self.launchd_dir.chmod(0o755)
        self.commands.statuses.extend([False, False, True])
        self.assertTrue(self.client.ensure_server())
        self.assertEqual(stat.S_IMODE(self.launchd_dir.stat().st_mode), 0o700)

    def test_working_directory_uses_home_at_call_time(self):
        self.commands.statuses.extend([False, False, True])
        home = Path(self.temp.name) / "changed-home"
        with patch.object(herdr.Path, "home", return_value=home):
            self.assertTrue(self.client.ensure_server())
        with self.plist.open("rb") as stream:
            config = plistlib.load(stream)
        self.assertEqual(config["WorkingDirectory"], str(home))

    def test_launch_succeeds_when_getcwd_fails(self):
        self.commands.statuses.extend([False, False, True])
        with patch.object(herdr.os, "getcwd", side_effect=FileNotFoundError("cwd removed")) as getcwd:
            try:
                started = self.client.ensure_server()
            except FileNotFoundError:
                self.fail("ensure_server must not need the caller's working directory")
        self.assertTrue(started)
        getcwd.assert_not_called()
        self.assertIn(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(self.plist)],
                      self.commands.launchctl_calls)

    def test_already_running_skips_launchctl(self):
        self.commands.statuses.append(True)
        self.assertFalse(self.client.ensure_server())
        self.assertEqual(self.commands.launchctl_calls, [])
        self.sleep.assert_not_called()

    def test_restart_after_exit_bootstraps_again(self):
        self.commands.statuses.extend([False, False, True, False, False, True])
        self.commands.print_stdout = "state = not running\n"
        self.assertTrue(self.client.ensure_server())
        self.assertTrue(self.client.ensure_server())
        one_launch = [
            ["launchctl", "print", self.target],
            ["launchctl", "bootout", self.target],
            ["launchctl", "print", self.target],
            ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(self.plist)],
        ]
        self.assertEqual(self.commands.launchctl_calls, one_launch * 2)

    def test_leftover_job_with_pid_is_allowed_to_start(self):
        self.commands.statuses.extend([False, False, False, True])
        self.commands.print_stdout = "state = running\n    pid = 4242\n"
        self.assertTrue(self.client.ensure_server())
        self.assertEqual(self.commands.launchctl_calls, [["launchctl", "print", self.target]])
        self.assertEqual(self.sleep.call_args_list, [call(0.2), call(0.2)])

    def test_bootstrap_failure_raises_server_start(self):
        self.commands.bootstrap_returncodes.extend([5, 5])
        with self.assertRaises(herdr.HerdrError) as raised:
            self.client.ensure_server()
        self.assertEqual(raised.exception.code, "server_start")
        self.assertEqual(self.commands.launchctl_calls[-2:], [
            ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(self.plist)],
            ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(self.plist)],
        ])
        self.assertEqual(self.sleep.call_args_list, [call(2.0)])

    def test_bootout_gone_at_once(self):
        self.commands.statuses.extend([False, False, True])
        self.assertTrue(self.client.ensure_server())
        self.assertEqual(self.commands.launchctl_calls, [
            ["launchctl", "print", self.target],
            ["launchctl", "bootout", self.target],
            ["launchctl", "print", self.target],
            ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(self.plist)],
        ])
        self.assertEqual(self.sleep.call_args_list, [call(0.2)])
        self.assertEqual(self.commands.print_kwargs, [
            {"capture_output": True, "text": True, "timeout": 15},
            {"capture_output": True, "text": True, "timeout": 15},
        ])

    def test_bootout_lingers_then_goes(self):
        self.commands.loaded_after_bootout = 3
        self.commands.statuses.extend([False, False, True])
        self.assertTrue(self.client.ensure_server())
        self.assertEqual(self.commands.launchctl_calls, [
            ["launchctl", "print", self.target],
            ["launchctl", "bootout", self.target],
            ["launchctl", "print", self.target],
            ["launchctl", "print", self.target],
            ["launchctl", "print", self.target],
            ["launchctl", "print", self.target],
            ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(self.plist)],
        ])
        self.assertEqual(self.commands.events[4:12], [
            ["launchctl", "print", self.target], call(0.2),
            ["launchctl", "print", self.target], call(0.2),
            ["launchctl", "print", self.target], call(0.2),
            ["launchctl", "print", self.target],
            ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(self.plist)],
        ])
        self.assertEqual(self.sleep.call_args_list, [call(0.2)] * 4)

    def test_bootout_never_unloads_at_bound(self):
        self.commands.loaded_after_bootout = None
        with self.assertRaises(herdr.HerdrError) as raised:
            self.client.ensure_server()
        self.assertEqual(self.commands.launchctl_calls.count(["launchctl", "print", self.target]), 101)
        self.assertEqual(self.sleep.call_args_list, [call(0.2)] * 99)
        self.assertFalse(any(argv[:2] == ["launchctl", "bootstrap"] for argv in self.commands.calls))
        self.assertEqual(raised.exception.code, "server_start")
        self.assertIn("still loaded", raised.exception.message)
        self.assertFalse(self.plist.exists())
        self.assertEqual(self.commands.calls.count([herdr.HERDR_BIN, "status", "server"]), 2)

    def test_bootstrap_retry_succeeds(self):
        self.commands.bootstrap_returncodes.extend([5, 0])
        self.commands.statuses.extend([False, False, True])
        try:
            started = self.client.ensure_server()
        except herdr.HerdrError:
            started = False
        bootstrap = ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(self.plist)]
        self.assertEqual(self.commands.launchctl_calls.count(bootstrap), 2)
        self.assertTrue(started)
        self.assertEqual(self.sleep.call_args_list, [call(2.0), call(0.2)])
        first = self.commands.events.index(bootstrap)
        self.assertEqual(self.commands.events[first:first + 5], [
            bootstrap, call(2.0), bootstrap, call(0.2), [herdr.HERDR_BIN, "status", "server"],
        ])

    def test_bootstrap_retry_failure_reports_second_stderr(self):
        self.commands.bootstrap_returncodes.extend([5, 7])
        with self.assertRaises(herdr.HerdrError) as raised:
            self.client.ensure_server()
        self.assertEqual(raised.exception.message, "bootstrap failure 2")
        self.assertEqual(raised.exception.code, "server_start")
        self.assertEqual(self.commands.launchctl_calls.count(
            ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(self.plist)]), 2)
        self.assertEqual(self.sleep.call_args_list, [call(2.0)])
        self.assertEqual(self.commands.calls.count([herdr.HERDR_BIN, "status", "server"]), 2)

    def test_bootstrap_retry_failure_with_empty_stderr_stops_before_readiness(self):
        self.commands.bootstrap_returncodes.extend([5, 7])
        self.commands.bootstrap_stderr = " \n\t"
        self.commands.statuses.extend([False, False, True])
        with self.assertRaises(herdr.HerdrError) as raised:
            self.client.ensure_server()
        self.assertEqual(raised.exception.code, "server_start")
        self.assertEqual(raised.exception.message, "")
        self.assertEqual(self.commands.launchctl_calls.count(
            ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(self.plist)]), 2)
        self.assertEqual(self.sleep.call_args_list, [call(2.0)])
        self.assertEqual(self.commands.calls.count([herdr.HERDR_BIN, "status", "server"]), 2)

    def test_timeout_after_fifty_polls(self):
        with self.assertRaises(herdr.HerdrError) as raised:
            self.client.ensure_server()
        self.assertEqual(raised.exception.code, "server_start")
        self.assertEqual(self.sleep.call_args_list, [call(0.2)] * 50)
        self.assertEqual(self.commands.calls.count([herdr.HERDR_BIN, "status", "server"]), 52)
        self.assertEqual(self.commands.launchctl_calls[-1],
                         ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(self.plist)])

    # integration: a real thread on a real flock, judged by timed joins on the real clock
    @integration_only
    def test_rechecks_status_after_waiting_for_lock(self):
        self.launchd_dir.mkdir(parents=True)
        result = []
        errors = []

        def ensure():
            try:
                result.append(self.client.ensure_server())
            except Exception as exc:
                errors.append(exc)

        with (self.launchd_dir / f"{self.label}.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            thread = threading.Thread(target=ensure)
            thread.start()
            try:
                self.assertTrue(self.commands.status_called.wait(1), "initial status was not checked")
                thread.join(0.2)
                self.assertTrue(thread.is_alive(), f"did not wait for lock: {errors!r}")
                self.assertEqual(self.commands.launchctl_calls, [])
                self.commands.running.set()
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
                thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(result, [False])
        self.assertEqual(self.commands.launchctl_calls, [])


class TestHerdrActionTracking(unittest.TestCase):
    def test_agent_get_returns_agent_and_uses_get_argv(self):
        agent = {"agent": "claude", "agent_status": "idle", "name": "a", "pane_id": "w1:p1",
                 "state_change_seq": 55, "terminal_id": "term_x", "workspace_id": "w1"}
        import json
        response = subprocess.CompletedProcess([], 0, json.dumps({"result": {"agent": agent}}), "")
        with patch.object(herdr.subprocess, "run", return_value=response) as run:
            self.assertEqual(herdr.Herdr("scratch").agent_get("w1:p1"), agent)
        self.assertEqual(run.call_args.args[0], [herdr.HERDR_BIN, "agent", "get", "w1:p1"])

    def test_last_action_tracks_mutations_after_call_but_not_reads_or_display(self):
        clock = [10.0]
        def command(argv, **kwargs):
            clock[0] += 1
            return subprocess.CompletedProcess(argv, 0, '{"result": {}}', "")
        with patch.object(herdr.subprocess, "run", side_effect=command), patch.object(herdr.time, "monotonic", lambda: clock[0]):
            client = herdr.Herdr("scratch")
            self.assertEqual(client.last_action, 0.0)
            for args in (("pane", "list"), ("agent", "list"), ("workspace", "list"), ("tab", "list"),
                         ("pane", "read", "p"), ("agent", "read", "p"), ("agent", "get", "p"),
                         ("status",), ("notification", "show", "x"), ("pane", "report-metadata", "p")):
                client.run(*args)
                self.assertEqual(client.last_action, 0.0, args)
            for args in (("pane", "run", "p", "x"), ("agent", "prompt", "p", "x"), ("pane", "close", "p")):
                client.run(*args)
                self.assertEqual(client.last_action, clock[0], args)
            client.run("pane", "list")
            self.assertEqual(client.last_action, clock[0] - 1)

    def test_last_action_uses_monotonic_not_wall_time(self):
        response = subprocess.CompletedProcess([], 0, '{"result": {}}', "")
        with (patch.object(herdr.subprocess, "run", return_value=response),
              patch.object(herdr.time, "time", return_value=1_000_000.0),
              patch.object(herdr.time, "monotonic", return_value=42.0)):
            client = herdr.Herdr("scratch")
            client.run("pane", "close", "p")
            self.assertEqual(client.last_action, 42.0)

    def test_last_action_tracks_failed_mutation_after_call(self):
        clock = [4.0]
        def command(argv, **kwargs):
            clock[0] = 8.0
            return subprocess.CompletedProcess(argv, 1, '{"error": {"code": "failed"}}', "")
        with patch.object(herdr.subprocess, "run", side_effect=command), patch.object(herdr.time, "monotonic", lambda: clock[0]):
            client = herdr.Herdr("scratch")
            with self.assertRaises(herdr.HerdrError):
                client.run("pane", "close", "p")
            self.assertEqual(client.last_action, 8.0)
        def timeout(argv, **kwargs):
            clock[0] = 12.0
            raise subprocess.TimeoutExpired(argv, 60)
        with patch.object(herdr.subprocess, "run", side_effect=timeout), patch.object(herdr.time, "monotonic", lambda: clock[0]):
            with self.assertRaises(subprocess.TimeoutExpired):
                client.run("pane", "close", "p")
            self.assertEqual(client.last_action, 12.0)


class TestLaunchdLabel(unittest.TestCase):
    def test_examples_and_distinct_labels(self):
        prefix = "com.codeteam.codeteam2.herdr."
        examples = {
            "codeteam": "codeteam",
            "a_b": "a_5fb",
            "a b": "a_20b",
            "a/b": "a_2fb",
            "a_20b": "a_5f20b",
            "AZaz09.-": "AZaz09.-",
            "é": "_c3_a9",
        }
        labels = [herdr.launchd_label(session) for session in examples]
        self.assertEqual(labels, [prefix + suffix for suffix in examples.values()])
        self.assertEqual(len(labels), len(set(labels)))
