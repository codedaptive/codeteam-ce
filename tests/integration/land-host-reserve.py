#!/usr/bin/env -S python3 -u
"""Stage 6 honours a host reservation, and host-reserve/host-release set and end one.
A zone integration test: codeteam-land's due_validation, cmd_host_reserve and cmd_host_release run against the real
HostReservation (share/codeteam_host_reservation.py), which persists each reservation as a file under a temp run/
folder. Stage 6's other collaborators are fakes, and the clock is a fixed NOW read in UTC, passed to the store
explicitly, so no result depends on the wall clock. tests/unit/land-host-reserve.py covers codeteam-land alone."""
import contextlib
import importlib.machinery
import importlib.util
import io
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "share"))
loader = importlib.machinery.SourceFileLoader("cl_host_reserve_zit", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)

from codeteam_host_reservation import HostReservation  # noqa: E402

REMOTE = {"host": "valhost", "path": "~/codeteam-work/landing/x", "suite": "make test"}
LOCAL = {"host": "local", "local": True, "path": "/tmp/v", "suite": "make test"}
C = "c0ffee1234567890"
NOW = 1794744000.0                      # 2026-11-15 12:00:00 UTC
CLOCK = SimpleNamespace(time=lambda: NOW, strftime=time.strftime, localtime=time.gmtime)


def team(stem="acme"):
    return SimpleNamespace(manifest=Path(f"/x/teams/{stem}.toml"), c=lambda key, default=None: default)


def due(tier, home, said):
    with patch.object(cl, "HERE", home / "bin"), patch.object(cl, "time", CLOCK), \
            patch.object(cl, "_RESERVATION_SAID", said), patch.object(cl, "halted", return_value=False), \
            patch.object(cl, "runner_unmoved", return_value=False), patch.object(cl, "stage6_target", return_value=C), \
            patch.object(cl, "alpha_cfg", return_value=tier), patch.object(cl, "validation_rows", return_value=[]), \
            patch.object(cl, "move_tip", return_value=None), patch.object(cl, "stage_rows", return_value=[]), \
            patch.object(cl, "validate_due", return_value=True), contextlib.redirect_stdout(io.StringIO()) as out:
        return cl.due_validation(team()), out.getvalue()


def run_cmd(fn, stem, home, **args):
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with patch.object(cl, "HERE", home / "bin"), patch.object(cl, "time", CLOCK), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            fn(team(stem), SimpleNamespace(**args))
        except SystemExit as ex:
            code = ex.code
    return code, out.getvalue(), err.getvalue()


def test_reserved_host_starts_no_run_and_says_why_once():
    with tempfile.TemporaryDirectory(prefix="land-host-reserve-") as tmp:
        home, said = Path(tmp), set()
        HostReservation(home / "run").take("valhost", 30, "lab", "S-208 timed run", NOW)
        assert due(REMOTE, home, said) == (
            None, "Stage 6 at c0ffee1234 waits: valhost is reserved by lab until 12:30 (S-208 timed run)\n")
        assert due(REMOTE, home, said) == (None, "")


def test_expired_reservation_holds_nothing():
    with tempfile.TemporaryDirectory(prefix="land-host-reserve-") as tmp:
        home = Path(tmp)
        HostReservation(home / "run").take("valhost", 1, "lab", "timed", NOW - 120)
        assert due(REMOTE, home, set()) == ((REMOTE, C), "")


def test_local_tier_ignores_a_reservation():
    with tempfile.TemporaryDirectory(prefix="land-host-reserve-") as tmp:
        home = Path(tmp)
        HostReservation(home / "run").take("local", 30, "lab", "timed", NOW)
        assert due(LOCAL, home, set()) == ((LOCAL, C), "")


def test_host_reserve_then_release_by_the_same_team():
    with tempfile.TemporaryDirectory(prefix="land-host-reserve-") as tmp:
        home = Path(tmp)
        assert run_cmd(cl.cmd_host_reserve, "lab", home, host="valhost", minutes=20.0, reason="S-208") == (
            0, "valhost reserved by lab until 12:20\n", "")
        assert HostReservation(home / "run").held("valhost", NOW) == {
            "host": "valhost", "by": "lab", "reason": "S-208", "since": NOW, "until": 1794745200.0}
        assert run_cmd(cl.cmd_host_release, "lab", home, host="valhost") == (0, "valhost released\n", "")
        assert HostReservation(home / "run").held("valhost", NOW) is None


def test_host_reserve_over_the_cap_and_release_by_another_team_are_refused():
    with tempfile.TemporaryDirectory(prefix="land-host-reserve-") as tmp:
        home = Path(tmp)
        assert run_cmd(cl.cmd_host_reserve, "lab", home, host="valhost", minutes=600.0, reason="long") == (
            5, "", "host-reserve: a reservation lasts more than 0 and at most 90 minutes, not 600\n")
        assert HostReservation(home / "run").held("valhost", NOW) is None
        run_cmd(cl.cmd_host_reserve, "lab", home, host="valhost", minutes=20.0, reason="S-208")
        assert run_cmd(cl.cmd_host_release, "acme", home, host="valhost") == (
            5, "", "host-release: valhost is reserved by another team, not acme\n")
        assert HostReservation(home / "run").held("valhost", NOW)["by"] == "lab"


if __name__ == "__main__":
    failed = 0
    for name, test in list(globals().items()):
        if name.startswith("test_") and callable(test):
            try:
                test()
                print(f"  PASS {name}")
            except Exception as exc:
                failed += 1
                print(f"  FAIL {name}: {type(exc).__name__}: {exc!r}")
    print(f"\n{f'{failed} failed' if failed else 'all passed'}")
    sys.exit(1 if failed else 0)
