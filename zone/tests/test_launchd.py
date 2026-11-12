import dataclasses
import importlib.machinery
import importlib.util
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
PLIST = Path("/tmp/sample.plist")


def load_launchd(name):
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / "share" / "codeteam_launchd.py"))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


launchd = load_launchd("codeteam_launchd_under_test")


class FakeLaunchctl:
    def __init__(self, prints=(), bootstraps=(), default_print=113, bootout=1):
        self.prints = iter(prints)
        self.bootstraps = iter(bootstraps)
        self.default_print = default_print
        self.bootout = bootout
        self.events = []
        self.calls = []

    def run(self, argv, **kwargs):
        self.events.append(("run", list(argv)))
        self.calls.append((list(argv), kwargs))
        assert len(self.calls) <= 300, "launchctl call bound exceeded"
        assert argv[0] == "launchctl"
        if argv[1] == "bootout":
            rc, stderr = self.bootout, "bootout failed"
        elif argv[1] == "print":
            rc, stderr = next(self.prints, self.default_print), ""
        elif argv[1] == "bootstrap":
            rc, stderr = next(self.bootstraps, (0, ""))
        else:
            raise AssertionError(f"unexpected launchctl command: {argv}")
        return SimpleNamespace(returncode=rc, stderr=stderr, stdout="")

    def sleep(self, seconds):
        self.events.append(("sleep", seconds))


def test_constants():
    assert (launchd.POLLS, launchd.POLL_S, launchd.RETRY_S) == (100, 0.2, 2.0)


def test_wait_gone_at_first_print():
    fake = FakeLaunchctl(prints=[113])
    assert launchd.wait_for_bootout("gui/501/sample", run=fake.run, sleep=fake.sleep) is True
    assert fake.events == [("run", ["launchctl", "print", "gui/501/sample"])]


def test_wait_loaded_twice_then_gone():
    fake = FakeLaunchctl(prints=[0, 0, 113])
    assert launchd.wait_for_bootout("gui/501/sample", run=fake.run, sleep=fake.sleep) is True
    assert fake.events == [
        ("run", ["launchctl", "print", "gui/501/sample"]),
        ("sleep", 0.2),
        ("run", ["launchctl", "print", "gui/501/sample"]),
        ("sleep", 0.2),
        ("run", ["launchctl", "print", "gui/501/sample"]),
    ]


def test_wait_never_gone_stops_at_default_bound():
    fake = FakeLaunchctl(default_print=0)
    assert launchd.wait_for_bootout("gui/501/sample", run=fake.run, sleep=fake.sleep) is False
    assert fake.events == [
        ("run", ["launchctl", "print", "gui/501/sample"]), ("sleep", 0.2),
    ] * 99 + [("run", ["launchctl", "print", "gui/501/sample"])]


def test_wait_respects_custom_poll_count_and_interval():
    fake = FakeLaunchctl(default_print=0)
    assert launchd.wait_for_bootout("target", run=fake.run, sleep=fake.sleep, polls=2, poll_s=0.5) is False
    assert fake.events == [
        ("run", ["launchctl", "print", "target"]),
        ("sleep", 0.5),
        ("run", ["launchctl", "print", "target"]),
    ]


def test_bootstrap_success_needs_no_retry():
    fake = FakeLaunchctl(bootstraps=[(0, "")])
    assert launchd.bootstrap("gui/501", PLIST, run=fake.run, sleep=fake.sleep) is None
    assert fake.events == [("run", ["launchctl", "bootstrap", "gui/501", "/tmp/sample.plist"])]


def test_bootstrap_failure_retries_once_then_succeeds():
    fake = FakeLaunchctl(bootstraps=[(5, "first"), (0, "")])
    assert launchd.bootstrap("gui/501", PLIST, run=fake.run, sleep=fake.sleep) is None
    assert fake.events == [
        ("run", ["launchctl", "bootstrap", "gui/501", "/tmp/sample.plist"]),
        ("sleep", 2.0),
        ("run", ["launchctl", "bootstrap", "gui/501", "/tmp/sample.plist"]),
    ]


def test_bootstrap_failure_returns_stripped_second_stderr():
    fake = FakeLaunchctl(bootstraps=[(5, "first"), (7, " bootstrap failure 2 \n")])
    assert launchd.bootstrap("gui/501", PLIST, run=fake.run, sleep=fake.sleep, retry_s=3.5) == "bootstrap failure 2"
    assert fake.events == [
        ("run", ["launchctl", "bootstrap", "gui/501", "/tmp/sample.plist"]),
        ("sleep", 3.5),
        ("run", ["launchctl", "bootstrap", "gui/501", "/tmp/sample.plist"]),
    ]


def test_bootstrap_empty_stderr_is_failure_not_success():
    fake = FakeLaunchctl(bootstraps=[(5, "first"), (7, "  \n")])
    assert launchd.bootstrap("gui/501", PLIST, run=fake.run, sleep=fake.sleep) == ""
    assert len(fake.calls) == 2


def test_reinstall_waits_for_unload_and_ignores_bootout_failure():
    fake = FakeLaunchctl(prints=[0, 0, 113], bootout=5)
    result = launchd.reinstall("sample", PLIST, 501, run=fake.run, sleep=fake.sleep)
    assert result == launchd.ReinstallResult(True, None)
    assert fake.events == [
        ("run", ["launchctl", "bootout", "gui/501/sample"]),
        ("run", ["launchctl", "print", "gui/501/sample"]),
        ("sleep", 0.2),
        ("run", ["launchctl", "print", "gui/501/sample"]),
        ("sleep", 0.2),
        ("run", ["launchctl", "print", "gui/501/sample"]),
        ("run", ["launchctl", "bootstrap", "gui/501", "/tmp/sample.plist"]),
    ]


def test_reinstall_retries_bootstrap_after_delay():
    fake = FakeLaunchctl(bootstraps=[(5, "first"), (0, "")])
    result = launchd.reinstall("sample", PLIST, 501, run=fake.run, sleep=fake.sleep)
    assert result == launchd.ReinstallResult(True, None)
    assert fake.events == [
        ("run", ["launchctl", "bootout", "gui/501/sample"]),
        ("run", ["launchctl", "print", "gui/501/sample"]),
        ("run", ["launchctl", "bootstrap", "gui/501", "/tmp/sample.plist"]),
        ("sleep", 2.0),
        ("run", ["launchctl", "bootstrap", "gui/501", "/tmp/sample.plist"]),
    ]


def test_reinstall_still_loaded_never_bootstraps():
    fake = FakeLaunchctl(default_print=0)
    result = launchd.reinstall("sample", PLIST, 501, run=fake.run, sleep=fake.sleep, wait_s=0.6, poll_s=0.2)
    assert result == launchd.ReinstallResult(False, "still loaded 0.6 s after bootout; not reinstalled")
    assert fake.events == [
        ("run", ["launchctl", "bootout", "gui/501/sample"]),
        ("run", ["launchctl", "print", "gui/501/sample"]),
        ("sleep", 0.2),
        ("run", ["launchctl", "print", "gui/501/sample"]),
        ("sleep", 0.2),
        ("run", ["launchctl", "print", "gui/501/sample"]),
    ]


def test_reinstall_default_wait_failure_reason():
    fake = FakeLaunchctl(default_print=0)
    result = launchd.reinstall("sample", PLIST, 501, run=fake.run, sleep=fake.sleep)
    assert result == launchd.ReinstallResult(False, "still loaded 20 s after bootout; not reinstalled")
    assert len(fake.calls) == 101
    assert all(argv[1] == "print" for argv, _ in fake.calls[1:])


@pytest.mark.parametrize("stderr,reason", [
    (" bootstrap failure 2 \n", "launchctl bootstrap failed: bootstrap failure 2"),
    ("", "launchctl bootstrap failed: "),
])
def test_reinstall_reports_second_bootstrap_failure(stderr, reason):
    fake = FakeLaunchctl(bootstraps=[(5, "first"), (7, stderr)])
    result = launchd.reinstall("sample", PLIST, 501, run=fake.run, sleep=fake.sleep)
    assert result == launchd.ReinstallResult(False, reason)
    assert fake.events == [
        ("run", ["launchctl", "bootout", "gui/501/sample"]),
        ("run", ["launchctl", "print", "gui/501/sample"]),
        ("run", ["launchctl", "bootstrap", "gui/501", "/tmp/sample.plist"]),
        ("sleep", 2.0),
        ("run", ["launchctl", "bootstrap", "gui/501", "/tmp/sample.plist"]),
    ]


@pytest.mark.parametrize("timeout,expected", [
    (None, {"capture_output": True, "text": True}),
    (15, {"capture_output": True, "text": True, "timeout": 15}),
])
@pytest.mark.parametrize("operation", ["wait", "bootstrap", "reinstall"])
def test_launchctl_kwargs_for_each_operation(operation, timeout, expected):
    fake = FakeLaunchctl(prints=[0, 113], bootstraps=[(5, "first"), (0, "")])
    if operation == "wait":
        assert launchd.wait_for_bootout("gui/501/sample", run=fake.run, sleep=fake.sleep, timeout=timeout) is True
    elif operation == "bootstrap":
        assert launchd.bootstrap("gui/501", PLIST, run=fake.run, sleep=fake.sleep, timeout=timeout) is None
    else:
        assert launchd.reinstall("sample", PLIST, 501, run=fake.run, sleep=fake.sleep, timeout=timeout).installed is True
    assert [kwargs for _, kwargs in fake.calls] == [expected] * len(fake.calls)
    assert len(fake.calls) >= 2


@pytest.mark.parametrize("operation", ["wait", "bootstrap", "reinstall"])
def test_default_seams_are_resolved_at_call_time(monkeypatch, operation):
    fake = FakeLaunchctl(prints=[0, 113], bootstraps=[(5, "first"), (0, "")])
    monkeypatch.setattr(subprocess, "run", fake.run)
    monkeypatch.setattr(time, "sleep", fake.sleep)
    if operation == "wait":
        assert launchd.wait_for_bootout("gui/501/sample") is True
        assert fake.events == [
            ("run", ["launchctl", "print", "gui/501/sample"]), ("sleep", 0.2),
            ("run", ["launchctl", "print", "gui/501/sample"]),
        ]
    elif operation == "bootstrap":
        assert launchd.bootstrap("gui/501", PLIST) is None
        assert fake.events == [
            ("run", ["launchctl", "bootstrap", "gui/501", "/tmp/sample.plist"]), ("sleep", 2.0),
            ("run", ["launchctl", "bootstrap", "gui/501", "/tmp/sample.plist"]),
        ]
    else:
        assert launchd.reinstall("sample", PLIST, 501) == launchd.ReinstallResult(True, None)
        assert fake.events == [
            ("run", ["launchctl", "bootout", "gui/501/sample"]),
            ("run", ["launchctl", "print", "gui/501/sample"]), ("sleep", 0.2),
            ("run", ["launchctl", "print", "gui/501/sample"]),
            ("run", ["launchctl", "bootstrap", "gui/501", "/tmp/sample.plist"]), ("sleep", 2.0),
            ("run", ["launchctl", "bootstrap", "gui/501", "/tmp/sample.plist"]),
        ]


def test_import_does_not_start_processes(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("process started during import")

    monkeypatch.setattr(subprocess, "run", fail)
    monkeypatch.setattr(subprocess, "Popen", fail)
    name = "codeteam_launchd_import_test"
    try:
        module = load_launchd(name)
        assert module.POLLS == 100
    finally:
        sys.modules.pop(name, None)


def test_result_is_frozen_and_success_reason_defaults_to_none():
    result = launchd.ReinstallResult(True)
    assert result.installed is True
    assert result.reason is None
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.installed = False
