"""bin/codeteam tmux_add with share/codeteam_tmux_terminal_start.py for real, with no tmux server.

Without a server, tmux_add has Terminal start one (osascript) so the sessions get a Terminal window's scheduling
priority, then waits for the session to appear. It waited 10 s, which a loaded machine misses (a v5.5 checkout's
validation at load 54.6: "tmux could not start Orc-Acme in T-Lead: error connecting to ..."), and it ignored a Terminal
that cannot be scripted, so that showed as the same socket error. tmux, osascript, tmux_setup and sleep are fakes;
nothing starts. It runs two files together, so it is a zone integration test; the unit tests of each are
tests/runtime/test_tmux_add.py and tests/unit/test_codeteam_tmux_terminal_start.py. Skipped unless
CODETEAM_TEST_GROUP=integration.
"""
import importlib.machinery
import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("CODETEAM_TEST_GROUP", "unit") != "integration",
                                reason="integration group only; run with CODETEAM_TEST_GROUP=integration")


ROOT = Path(__file__).resolve().parents[2]
NEW_SESSION = ("tmux", "new-session", "-d", "-s", "team", "-n", "worker", "-x", "220", "-y", "60",
               "/bin/bash -l '/tmp/launch.sh'")


@pytest.fixture(scope="module")
def codeteam():
    environment = os.environ.copy()
    dont_write_bytecode = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        if "herdr" in os.environ.get("SSH_AUTH_SOCK", ""):
            os.environ.pop("SSH_AUTH_SOCK")
        for name in ("CT_COMPACT_HOURS", "CT_EXIT_HOURS", "CT_SWAP_IDLE_MIN", "CT_API_RESUME_PER_RUN"):
            os.environ.pop(name, None)
        loader = importlib.machinery.SourceFileLoader("codeteam", str(ROOT / "bin" / "codeteam"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = dont_write_bytecode
        os.environ.clear()
        os.environ.update(environment)


@pytest.fixture
def calls(codeteam, monkeypatch):
    """tmux has no server; after osascript ran, has-session succeeds from poll number `appear_at` (None: never)."""
    recorded = SimpleNamespace(events=[], osa=[], osa_ok=True, appear_at=1, polls=0, warned=[])

    def tmux(*args):
        recorded.events.append(("tmux", *args))
        if args[0] == "list-sessions":
            return SimpleNamespace(returncode=1, stdout="", stderr="no server running")
        if args[0] == "has-session":
            if recorded.osa and recorded.osa_ok:
                recorded.polls += 1
                up = recorded.appear_at is not None and recorded.polls >= recorded.appear_at
                return SimpleNamespace(returncode=0 if up else 1, stdout="", stderr="" if up else "error connecting")
            return SimpleNamespace(returncode=1, stdout="", stderr="error connecting")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def osa(script):
        recorded.osa.append(script)
        return recorded.osa_ok

    monkeypatch.setattr(codeteam, "tmux", tmux)
    monkeypatch.setattr(codeteam, "osa", osa)
    monkeypatch.setattr(codeteam, "warn", recorded.warned.append)
    monkeypatch.setattr(codeteam, "tmux_setup", lambda: recorded.events.append(("setup",)))
    monkeypatch.setattr(codeteam.time, "sleep", lambda _: None)
    monkeypatch.setattr(codeteam.sys, "platform", "darwin")
    monkeypatch.delenv("CODETEAM_NO_TERMINAL", raising=False)
    return recorded


def test_no_terminal_starts_a_detached_session(codeteam, calls, monkeypatch):
    monkeypatch.setenv("CODETEAM_NO_TERMINAL", "1")
    codeteam.tmux_add("team", "worker", "/tmp/launch.sh")
    assert calls.osa == []
    assert calls.events == [
        ("tmux", "has-session", "-t", "=team"),
        ("tmux", "list-sessions"),
        NEW_SESSION,
        ("setup",),
        ("tmux", "set-option", "-w", "-t", "=team:worker", "automatic-rename", "off"),
        ("tmux", "set-option", "-w", "-t", "=team:worker", "allow-rename", "off"),
    ]


def test_without_the_override_terminal_starts_the_server(codeteam, calls):
    codeteam.tmux_add("team", "worker", "/tmp/launch.sh")
    assert len(calls.osa) == 1
    assert "do script" in calls.osa[0] and "new-session" in calls.osa[0]
    assert NEW_SESSION not in calls.events
    assert ("setup",) in calls.events


def test_a_session_that_appears_after_the_old_ten_seconds_is_still_waited_for(codeteam, calls):
    calls.appear_at = 41 + 100              # the old wait gave up after 40 polls of 0.25 s
    codeteam.tmux_add("team", "worker", "/tmp/launch.sh")
    assert ("setup",) in calls.events
    assert calls.polls >= calls.appear_at   # the loop's polls, then the one check after it


def test_a_terminal_that_cannot_be_scripted_falls_back_to_a_detached_server_and_says_so(codeteam, calls):
    calls.osa_ok = False
    codeteam.tmux_add("team", "worker", "/tmp/launch.sh")
    assert NEW_SESSION in calls.events and ("setup",) in calls.events
    assert len(calls.warned) == 1 and "Terminal could not be scripted" in calls.warned[0]


def test_a_session_that_never_appears_names_the_wait_not_only_the_socket(codeteam, calls):
    calls.appear_at = None
    with pytest.raises(SystemExit) as stop:
        codeteam.tmux_add("team", "worker", "/tmp/launch.sh")
    text = str(stop.value)
    assert "Terminal ran" in text and f"{codeteam.TMUX_START_WAIT_S} s" in text and "error connecting" in text
