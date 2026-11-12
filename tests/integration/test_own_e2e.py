"""Integration: bin/codeteam-own with real processes. A harness rebinds own.SSH to a stub ssh script, so the
wrapper's real posix_spawn (or exec fallback) starts it: status and stdio pass through, a command that cannot start is
exit 127, TERM reaches the command, /usr/bin/timeout inside it ends the command, and a refused command never starts.
Joins: codeteam-own's main(), the macOS spawn call, /usr/bin/timeout and a child process. Moved out of tests/own.py,
whose unit cases are now tests/unit/own.py.
Skipped unless CODETEAM_TEST_GROUP=integration."""
import os
import shlex
import signal
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("CODETEAM_TEST_GROUP", "unit") != "integration",
                                reason="integration group only; run with CODETEAM_TEST_GROUP=integration")

HOME = Path(__file__).resolve().parents[2]
OWN = str(HOME / "bin" / "codeteam-own")
HARNESS = """import importlib.machinery, importlib.util, sys
loader = importlib.machinery.SourceFileLoader('own', %r)
spec = importlib.util.spec_from_loader('own', loader)
own = importlib.util.module_from_spec(spec)
loader.exec_module(own)
own.SSH = sys.argv[1]
sys.exit(own.main(sys.argv[2:]))
""" % OWN
STUB = """#!/bin/sh
case "$1" in
    stdio)
        cat
        printf 'err\\n' >&2
        exit 7
        ;;
    term)
        sleep 30 &
        child=$!
        trap 'kill "$child"; wait "$child"; exit 3' TERM
        printf 'ready\\n'
        wait "$child"
        ;;
    timeout)
        exec sleep 20
        ;;
    *) exit 99 ;;
esac
"""


@pytest.fixture
def stub(tmp_path):
    path = tmp_path / "ssh"
    path.write_text(STUB)
    path.chmod(0o755)
    return path


@pytest.fixture
def stubenv(stub):
    return dict(os.environ, PATH=str(stub.parent) + os.pathsep + os.environ.get("PATH", ""))


def harness(ssh, *argv, **kw):
    return subprocess.run([sys.executable, "-c", HARNESS, str(ssh), *argv], capture_output=True, **kw)


def test_status_stdin_stdout_and_stderr_pass_through(stub, stubenv):
    r = harness(stub, "ssh", "stdio", input="in\n", text=True, env=stubenv)
    assert (r.returncode, r.stdout, r.stderr) == (7, "in\n", "err\n")


def test_an_absolute_ssh_path_passes_status_and_stdio_through(stub, stubenv):
    r = harness(stub, str(stub), "stdio", input="in\n", text=True, env=stubenv)
    assert (r.returncode, r.stdout, r.stderr) == (7, "in\n", "err\n")


def test_a_command_that_cannot_start_is_exit_127_with_its_name(stubenv):
    r = harness("/no/such/dir/ssh", "ssh", text=True, env=stubenv)
    assert r.returncode == 127 and "/no/such/dir/ssh" in r.stderr


def test_a_non_approved_missing_ssh_path_is_refused(stubenv):
    r = subprocess.run([OWN, "/no/such/dir/ssh"], capture_output=True, text=True, env=stubenv)
    assert r.returncode == 2 and "/no/such/dir/ssh" in r.stderr


def test_term_is_passed_on_to_the_command(stub, stubenv):
    p = subprocess.Popen([sys.executable, "-c", HARNESS, str(stub), "ssh", "term"], stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, env=stubenv)
    try:
        assert p.stdout.readline() == "ready\n"
        p.send_signal(signal.SIGTERM)
        assert p.wait(timeout=10) == 3
    finally:
        if p.poll() is None:
            p.terminate()
            p.wait(timeout=10)
        p.stdout.close()
        p.stderr.close()


def test_a_time_limit_inside_it_ends_the_command_with_exit_124(stub, stubenv):
    r = harness(stub, "/usr/bin/timeout", "1", "ssh", "timeout", env=stubenv)
    assert r.returncode == 124


@pytest.mark.parametrize("argv, name", [
    (["/bin/sh", "-c", "TOUCH"], "/bin/sh"),
    (["/usr/bin/timeout", "5", "/bin/sh", "-c", "TOUCH"], "/bin/sh"),
    (["/usr/bin/timeout"], "/usr/bin/timeout"),
])
def test_a_refused_command_is_never_started(tmp_path, stubenv, argv, name):
    marker = tmp_path / "marker"
    argv = [f"touch {shlex.quote(str(marker))}" if a == "TOUCH" else a for a in argv]
    r = subprocess.run([OWN, *argv], capture_output=True, text=True, env=stubenv)
    assert r.returncode == 2 and name in r.stderr and not marker.exists()
