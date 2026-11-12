#!/usr/bin/env -S python3 -u
"""Check the command rule's cases and pinning to /usr/bin/ssh through command() and a fake libc; other checks cover
refusals and codeteam-land's use of the wrapper. The checks that start real processes (status, stdio, TERM forwarding,
the time limit) are in the integration group: tests/integration/test_own_e2e.py. The network effect was measured in a
launchd job."""
import contextlib
import importlib.machinery
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

HOME = Path(__file__).resolve().parents[2]
OWN = str(HOME / "bin" / "codeteam-own")
fails = 0


def t(label, cond, detail=""):
    global fails
    print(("  PASS " if cond else "  FAIL ") + label + ("" if cond else f"  [{detail}]"))
    fails += not cond


ld = importlib.machinery.SourceFileLoader("own", OWN)
sp = importlib.util.spec_from_loader("own", ld)
own = importlib.util.module_from_spec(sp)
ld.exec_module(own)
refused = getattr(own, "refused", None)

cases = [
    ("allows ssh with arguments", ["ssh", "h", "true"], None),
    ("allows an absolute ssh path", ["/usr/bin/ssh", "h"], None),
    ("refuses an arbitrary path ending in ssh", ["/tmp/x/ssh"], "/tmp/x/ssh"),
    ("refuses a relative ssh path", ["./ssh"], "./ssh"),
    ("refuses a Homebrew ssh path", ["/opt/homebrew/bin/ssh"], "/opt/homebrew/bin/ssh"),
    ("refuses timeout wrapping an arbitrary ssh path", ["/usr/bin/timeout", "5", "/tmp/x/ssh"], "/tmp/x/ssh"),
    ("allows timeout wrapping ssh", ["/usr/bin/timeout", "900", "ssh", "-o", "BatchMode=yes", "h"], None),
    ("allows timeout wrapping an absolute ssh path", ["/usr/bin/timeout", "30", "/usr/bin/ssh", "h"], None),
    ("refuses a non-ssh program", ["/bin/sh", "-c", "x"], "/bin/sh"),
    ("refuses a non-ssh program wrapped in timeout", ["/usr/bin/timeout", "5", "/bin/sh"], "/bin/sh"),
    ("refuses timeout without a duration or command", ["/usr/bin/timeout"], ""),
    ("refuses timeout without a command", ["/usr/bin/timeout", "5"], ""),
    ("refuses a path whose basename only contains ssh", ["/x/myssh"], "/x/myssh"),
    ("refuses sshd", ["sshd"], "sshd"),
    ("refuses timeout without its required absolute path", ["timeout", "5", "ssh"], "timeout"),
    ("refuses an option in place of the timeout duration", ["/usr/bin/timeout", "-k", "5", "ssh"], ""),
    ("refuses an empty command", [], ""),
]
for label, argv, expected in cases:
    if refused is None:
        t(label, False, "refused API is missing")
        continue
    result = refused(argv)
    if expected is None:
        t(label, result is None, result)
    else:
        t(label, isinstance(result, str) and bool(result) and expected in result, result)

with patch.object(own, "SSH", "/test/ssh", create=True):
    accepted = refused(["/test/ssh", "h"])
    result = refused(["/usr/bin/ssh", "h"])
    t("refused rejects the old SSH path after SSH changes",
      accepted is None and isinstance(result, str) and "/usr/bin/ssh" in result, (accepted, result))

command = getattr(own, "command", None)
for label, argv, expected in (
    ("command pins bare ssh", ["ssh", "h", "true"], ["/usr/bin/ssh", "h", "true"]),
    ("command preserves absolute ssh", ["/usr/bin/ssh", "h"], ["/usr/bin/ssh", "h"]),
    ("command pins ssh under timeout", ["/usr/bin/timeout", "900", "ssh", "-o", "BatchMode=yes", "h"],
     ["/usr/bin/timeout", "900", "/usr/bin/ssh", "-o", "BatchMode=yes", "h"]),
):
    result = command(argv) if command is not None else None
    t(label, result == expected, result if command is not None else "command API is missing")

with patch.object(own, "SSH", "/test/ssh", create=True):
    result = command(["ssh", "h"]) if command is not None else None
    t("command reads SSH at call time", result == ["/test/ssh", "h"],
      result if command is not None else "command API is missing")

for duration in ("0", "1", "900", "1.5", "1s", "2m", "3h", "4d", "0.25s"):
    result = refused(["/usr/bin/timeout", duration, "ssh"])
    t(f"allows duration {duration!r}", result is None, result)
for duration in ("", "-k", "-1", "+1", ".5", "1.", "1ms", "1e2", "1S", " 1", "1\n"):
    result = refused(["/usr/bin/timeout", duration, "ssh"])
    t(f"refuses duration {duration!r}", isinstance(result, str) and "/usr/bin/timeout" in result, result)
for argv in (["/usr/bin/timeout"], ["/usr/bin/timeout", "5"]):
    result = refused(argv)
    t(f"missing timeout command is named for {argv!r}",
      isinstance(result, str) and "/usr/bin/timeout" in result and "no command" in result, result)

for argv, name in ((["/bin/sh"], "/bin/sh"),
                   (["/usr/bin/timeout", "5", "/bin/sh"], "/bin/sh"),
                   (["/usr/bin/timeout"], "/usr/bin/timeout"), ([], "no command")):
    stderr = io.StringIO()
    with patch.object(own.ctypes, "CDLL") as setup, patch.object(own.os, "execvp") as execute:
        with contextlib.redirect_stderr(stderr):
            code = own.main(argv)
        t(f"main refuses {argv!r} before setup or exec",
          code == 2 and name in stderr.getvalue() and "only ssh" in stderr.getvalue()
          and not setup.called and not execute.called, (code, stderr.getvalue()))

stubdir = Path(tempfile.mkdtemp())
try:
    stub = stubdir / "ssh"
    stub.write_text("""#!/bin/sh
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
""")
    stub.chmod(0o755)
    stubenv = dict(os.environ, PATH=str(stubdir) + os.pathsep + os.environ.get("PATH", ""))

    class FakeLibc:
        def __init__(self):
            self.spawned = []
            self.searched = []

        def responsibility_spawnattrs_setdisclaim(self, attr, flag):
            return 0

        def posix_spawnattr_init(self, attr):
            return 0

        def posix_spawn(self, pid, path, actions, attr, args, env):
            self.spawned.append((path, list(args)))
            return 2

        def posix_spawnp(self, pid, path, actions, attr, args, env):
            self.searched.append((path, list(args)))
            return 2

    for label, argv, expected_path, expected_args in (
        ("main pins ssh despite a PATH stub", ["ssh", "h"], b"/usr/bin/ssh", [b"/usr/bin/ssh", b"h", None]),
        ("main pins ssh under timeout despite a PATH stub", ["/usr/bin/timeout", "900", "ssh", "-o", "BatchMode=yes", "h"],
         b"/usr/bin/timeout", [b"/usr/bin/timeout", b"900", b"/usr/bin/ssh", b"-o", b"BatchMode=yes", b"h", None]),
    ):
        libc = FakeLibc()
        stderr = io.StringIO()
        with patch.dict(os.environ, stubenv), patch.object(own.ctypes.util, "find_library", return_value="libc"), \
             patch.object(own.ctypes, "CDLL", return_value=libc), contextlib.redirect_stderr(stderr):
            code = own.main(argv)
        t(label, code == 127 and libc.spawned == [(expected_path, expected_args)] and not libc.searched
          and os.fsencode(stub) not in expected_args and os.fsencode(stub) != expected_path
          and os.fsdecode(expected_path) in stderr.getvalue(), (code, libc.spawned, libc.searched, stderr.getvalue()))

    class ExecCalled(Exception):
        pass

    with patch.object(own.ctypes.util, "find_library", return_value="libc"), \
         patch.object(own.ctypes, "CDLL", side_effect=OSError("unavailable")), \
         patch.object(own.os, "execv", side_effect=ExecCalled) as execute, \
         patch.object(own.os, "execvp", side_effect=ExecCalled) as search:
        try:
            own.main(["ssh", "h"])
        except ExecCalled:
            pass
        t("fallback executes absolute ssh without PATH", execute.call_args_list == [(("/usr/bin/ssh", ["/usr/bin/ssh", "h"]), {})]
          and not search.called, (execute.call_args_list, search.call_args_list))

    # The checks that start real processes (the stub harness: stdio, a command that cannot start, TERM, the time
    # limit; and the refusals run as a real process) are integration tests: tests/integration/test_own_e2e.py.
finally:
    shutil.rmtree(stubdir)

ld = importlib.machinery.SourceFileLoader("cl", str(HOME / "bin" / "codeteam-land"))
sp = importlib.util.spec_from_loader("cl", ld)
cl = importlib.util.module_from_spec(sp)
sys.modules["cl"] = cl
env = os.environ.pop("GIT_SSH_COMMAND", None)
ld.exec_module(cl)
t("git's ssh goes through it, with its time limit and BatchMode",
  os.environ["GIT_SSH_COMMAND"].startswith(OWN + " /usr/bin/timeout 900 ssh ") and "BatchMode=yes" in os.environ["GIT_SSH_COMMAND"],
  os.environ["GIT_SSH_COMMAND"])
seen = []
real = cl.subprocess.run
cl.subprocess.run = lambda cmd, **k: seen.append((cmd, k)) or subprocess.CompletedProcess(cmd, 0, "", "")
try:
    cl.ssh({"host": "buildhost"}, "true", timeout=30, input="x")
finally:
    cl.subprocess.run = real
cmd, k = seen[0]
t("the tool's own ssh goes through it, limited inside", cmd[:4] == [OWN, "/usr/bin/timeout", "30", "ssh"] and cmd[-2:] == ["buildhost", "true"]
  and k.get("input") == "x" and k.get("timeout") == 90, (cmd, k))
print("all passed" if not fails else f"{fails} failed")
sys.exit(1 if fails else 0)
