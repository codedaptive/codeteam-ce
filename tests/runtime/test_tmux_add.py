"""bin/codeteam tmux_add alone (D524): it opens a window in a session that exists, otherwise it asks
share/codeteam_tmux_terminal_start.py to have Terminal start the server, and it starts the server detached when that
answers None. tmux, tmux_setup and the share module are fakes; nothing starts. The two files together:
tests/integration/test_tmux_add_terminal.py.
"""
import importlib.machinery
import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
CMD = "/bin/bash -l '/tmp/launch.sh'"
NEW_SESSION = ("tmux", "new-session", "-d", "-s", "team", "-n", "worker", "-x", "220", "-y", "60", CMD)
RENAME_OFF = [("tmux", "set-option", "-w", "-t", "=team:worker", "automatic-rename", "off"),
              ("tmux", "set-option", "-w", "-t", "=team:worker", "allow-rename", "off")]


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
    """has-session answers `session_up`; new-window and new-session answer `start_rc`; the share module's
    tmux_terminal_start records its arguments and answers `terminal`."""
    recorded = SimpleNamespace(events=[], session_up=False, start_rc=0, terminal=None, terminal_calls=[])

    def tmux(*args):
        recorded.events.append(("tmux", *args))
        if args[0] == "has-session":
            return SimpleNamespace(returncode=0 if recorded.session_up else 1, stdout="", stderr="")
        if args[0] in ("new-window", "new-session"):
            return SimpleNamespace(returncode=recorded.start_rc, stdout="", stderr="no space for new pane")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def tmux_terminal_start(*args, **kwargs):
        recorded.terminal_calls.append((args, kwargs))
        recorded.events.append(("terminal",))
        return recorded.terminal

    monkeypatch.setattr(codeteam, "tmux", tmux)
    monkeypatch.setattr(codeteam, "tmux_setup", lambda: recorded.events.append(("setup",)))
    monkeypatch.setattr(codeteam.sys, "path", list(sys.path))
    monkeypatch.setitem(sys.modules, "codeteam_tmux_terminal_start",
                        SimpleNamespace(tmux_terminal_start=tmux_terminal_start))
    return recorded


def test_a_session_that_exists_gets_a_window_and_terminal_is_not_asked(codeteam, calls):
    calls.session_up = True
    codeteam.tmux_add("team", "worker", "/tmp/launch.sh")
    assert calls.events == [("tmux", "has-session", "-t", "=team"),
                            ("tmux", "new-window", "-d", "-t", "=team:", "-n", "worker", CMD), *RENAME_OFF]


def test_terminal_is_asked_with_the_session_the_command_and_a_60_s_wait(codeteam, calls):
    calls.terminal = SimpleNamespace(returncode=0, stdout="", stderr="")
    codeteam.tmux_add("team", "worker", "/tmp/launch.sh")
    (args, kwargs), = calls.terminal_calls
    assert args == ("team", "worker", CMD)
    assert (kwargs["wait_s"], kwargs["terminal_app"]) == (60, "Terminal")
    assert kwargs["tmux_bin"] == codeteam.TMUX and kwargs["socket"] == codeteam.TMUX_SOCKET
    assert kwargs["tmux"] is codeteam.tmux


def test_a_server_terminal_started_is_set_up_and_no_detached_server_starts(codeteam, calls):
    calls.terminal = SimpleNamespace(returncode=0, stdout="", stderr="")
    codeteam.tmux_add("team", "worker", "/tmp/launch.sh")
    assert calls.events == [("tmux", "has-session", "-t", "=team"), ("terminal",), ("setup",), *RENAME_OFF]


def test_without_terminal_the_server_starts_detached_and_is_set_up(codeteam, calls):
    codeteam.tmux_add("team", "worker", "/tmp/launch.sh")
    assert calls.events == [("tmux", "has-session", "-t", "=team"), ("terminal",), NEW_SESSION, ("setup",),
                            *RENAME_OFF]


def test_a_detached_start_that_fails_exits_with_tmux_s_error_and_sets_nothing_up(codeteam, calls):
    calls.start_rc = 1
    with pytest.raises(SystemExit) as stop:
        codeteam.tmux_add("team", "worker", "/tmp/launch.sh")
    assert str(stop.value) == "tmux could not start worker in team: no space for new pane"
    assert ("setup",) not in calls.events


def test_a_window_that_fails_exits_with_tmux_s_error(codeteam, calls):
    calls.session_up, calls.start_rc = True, 1
    with pytest.raises(SystemExit) as stop:
        codeteam.tmux_add("team", "worker", "/tmp/launch.sh")
    assert str(stop.value) == "tmux could not start worker in team: no space for new pane"
    assert calls.terminal_calls == []
