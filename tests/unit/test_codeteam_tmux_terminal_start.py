"""share/codeteam_tmux_terminal_start.py alone (D505; D524): with no tmux server on macOS, Terminal starts one and the
session is waited for; otherwise, or when Terminal cannot be scripted, None tells tmux_add to start it detached.
tmux, osascript, warn and sleep are fakes; nothing starts. tmux_add with it: tests/integration/test_tmux_add_terminal.py.
"""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("codeteam_tmux_terminal_start",
                                              ROOT / "share" / "codeteam_tmux_terminal_start.py")
module = importlib.util.module_from_spec(spec)
dont_write_bytecode = sys.dont_write_bytecode
try:
    sys.dont_write_bytecode = True
    spec.loader.exec_module(module)
finally:
    sys.dont_write_bytecode = dont_write_bytecode


@pytest.fixture
def fakes(monkeypatch):
    """No server (list-sessions fails) unless `server`; after osascript ran, has-session succeeds from poll
    `appear_at` (None: never)."""
    f = SimpleNamespace(events=[], osa=[], osa_ok=True, server=False, appear_at=1, polls=0, warned=[], sleeps=0)

    def tmux(*args):
        f.events.append(args)
        if args[0] == "list-sessions":
            return SimpleNamespace(returncode=0 if f.server else 1, stdout="", stderr="no server running")
        if args[0] == "has-session" and f.osa and f.osa_ok:
            f.polls += 1
            up = f.appear_at is not None and f.polls >= f.appear_at
            return SimpleNamespace(returncode=0 if up else 1, stdout="", stderr="" if up else "error connecting")
        return SimpleNamespace(returncode=1, stdout="", stderr="error connecting")

    def osa(script):
        f.osa.append(script)
        return f.osa_ok

    def sleep(_):
        f.sleeps += 1

    f.tmux, f.osa_call, f.warn = tmux, osa, f.warned.append
    monkeypatch.setattr(module.sys, "platform", "darwin")
    monkeypatch.setattr(module.time, "sleep", sleep)
    monkeypatch.delenv("CODETEAM_NO_TERMINAL", raising=False)
    return f


def start(f, cmd="/bin/bash -l /tmp/launch.sh"):
    return module.tmux_terminal_start("team", "worker", cmd, tmux=f.tmux, osa=f.osa_call, warn=f.warn,
                                      tmux_bin="tmux", socket="sock", terminal_app="Terminal", wait_s=60)


def test_a_running_server_needs_no_terminal(fakes):
    fakes.server = True
    assert start(fakes) is None
    assert fakes.events == [("list-sessions",)] and fakes.osa == []


def test_off_macos_terminal_is_not_used(fakes, monkeypatch):
    monkeypatch.setattr(module.sys, "platform", "linux")
    assert start(fakes) is None
    assert fakes.osa == []


def test_codeteam_no_terminal_skips_terminal_after_asking_for_a_server(fakes, monkeypatch):
    monkeypatch.setenv("CODETEAM_NO_TERMINAL", "1")
    assert start(fakes) is None
    assert fakes.events == [("list-sessions",)] and fakes.osa == []


def test_terminal_runs_tmux_new_session_on_the_socket_and_the_session_is_returned(fakes):
    r = start(fakes)
    assert fakes.osa == ['tell application "Terminal" to do script "tmux -L sock new-session -d -s team -n worker '
                         "-x 220 -y 60 '/bin/bash -l /tmp/launch.sh'; exit\""]
    assert r.returncode == 0 and fakes.events[-1] == ("has-session", "-t", "=team")


def test_double_quotes_in_the_command_are_escaped_for_applescript(fakes):
    start(fakes, cmd='echo "hi"')
    assert fakes.osa == ['tell application "Terminal" to do script "tmux -L sock new-session -d -s team -n worker '
                         "-x 220 -y 60 'echo \\\"hi\\\"'; exit\""]


def test_a_session_that_appears_after_the_old_ten_seconds_is_still_waited_for(fakes):
    fakes.appear_at = 141                     # the old wait gave up after 40 polls of 0.25 s
    assert start(fakes).returncode == 0
    assert fakes.polls == 142                 # 141 polls in the loop, then the one check after it


def test_a_terminal_that_cannot_be_scripted_warns_and_leaves_the_start_to_the_caller(fakes):
    fakes.osa_ok = False
    assert start(fakes) is None
    assert fakes.warned == ["Terminal could not be scripted to start tmux for team; starting it detached, "
                            "at a background process's priority"]
    assert ("has-session", "-t", "=team") not in fakes.events


def test_a_session_that_never_appears_exits_naming_the_wait_after_240_polls(fakes):
    fakes.appear_at = None
    with pytest.raises(SystemExit) as stop:
        start(fakes)
    assert str(stop.value) == ("tmux could not start worker in team: Terminal ran the start, but no session team "
                               "after 60 s (error connecting)")
    assert fakes.sleeps == 240
