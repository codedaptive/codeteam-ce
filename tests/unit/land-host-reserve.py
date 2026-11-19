#!/usr/bin/env -S python3 -u
"""Stage 6 starts no new run on a reserved host, and host-reserve/host-release set and end a reservation.
A zone unit test of codeteam-land alone: the reservation store (HostReservation, in
share/codeteam_host_reservation.py) is a fake recording its calls, Stage 6's other collaborators are fakes, and the
clock is a fixed NOW read in UTC. tests/integration/land-host-reserve.py runs the same paths on the real store."""
import contextlib
import importlib.machinery
import importlib.util
import io
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "share"))
loader = importlib.machinery.SourceFileLoader("cl_host_reserve", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)

REMOTE = {"host": "valhost", "path": "~/codeteam-work/landing/x", "suite": "make test"}
LOCAL = {"host": "local", "local": True, "path": "/tmp/v", "suite": "make test"}
C = "c0ffee1234567890"
NOW = 1794744000.0                      # 2026-11-15 12:00:00 UTC
HERE = Path("/x/codeteam/bin")
CLOCK = SimpleNamespace(time=lambda: NOW, strftime=time.strftime, localtime=time.gmtime)
HELD = {"host": "valhost", "by": "lab", "reason": "S-208 timed run", "since": NOW, "until": NOW + 1800}


class FakeStore:
    """Stands in for the HostReservation class: calling it gives itself, and each method call is recorded."""

    def __init__(self, held=None, taken=None, take_error=None, released=True):
        self.row, self.taken, self.take_error, self.released = held, taken, take_error, released
        self.calls = []

    def __call__(self, run_dir):
        self.calls.append(("open", run_dir))
        return self

    def held(self, host, now):
        self.calls.append(("held", host, now))
        return self.row

    def take(self, host, minutes, by, reason, now):
        self.calls.append(("take", host, minutes, by, reason, now))
        if self.take_error:
            raise ValueError(self.take_error)
        return self.taken

    def release(self, host, by, now):
        self.calls.append(("release", host, by, now))
        return self.released


def team(stem="acme"):
    return SimpleNamespace(manifest=Path(f"/x/teams/{stem}.toml"), c=lambda key, default=None: default)


def due(tier, store, said, commit=C):
    with patch.object(cl, "HERE", HERE), patch.object(cl, "time", CLOCK), patch.object(cl, "HostReservation", store), \
            patch.object(cl, "_RESERVATION_SAID", said), patch.object(cl, "halted", return_value=False), \
            patch.object(cl, "runner_unmoved", return_value=False), \
            patch.object(cl, "stage6_target", return_value=commit), \
            patch.object(cl, "alpha_cfg", return_value=tier), patch.object(cl, "validation_rows", return_value=[]), \
            patch.object(cl, "move_tip", return_value=None), patch.object(cl, "stage_rows", return_value=[]), \
            patch.object(cl, "validate_due", return_value=True), contextlib.redirect_stdout(io.StringIO()) as out:
        return cl.due_validation(team()), out.getvalue()


def run_cmd(fn, stem, store, **args):
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with patch.object(cl, "HERE", HERE), patch.object(cl, "time", CLOCK), patch.object(cl, "HostReservation", store), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            fn(team(stem), SimpleNamespace(**args))
        except SystemExit as ex:
            code = ex.code
    return code, out.getvalue(), err.getvalue()


def test_unreserved_host_is_due():
    store = FakeStore()
    assert due(REMOTE, store, set()) == ((REMOTE, C), "")
    assert store.calls == [("open", Path("/x/codeteam/run")), ("held", "valhost", NOW)]


def test_reserved_host_starts_no_run_and_says_why_once_per_commit():
    store, said = FakeStore(held=HELD), set()
    line = "Stage 6 at c0ffee1234 waits: valhost is reserved by lab until 12:30 (S-208 timed run)\n"
    assert due(REMOTE, store, said) == (None, line)
    assert due(REMOTE, store, said) == (None, "")
    assert due(REMOTE, store, said, commit="beef5678901234") == (
        None, "Stage 6 at beef567890 waits: valhost is reserved by lab until 12:30 (S-208 timed run)\n")


def test_local_tier_never_asks_about_a_reservation():
    store = FakeStore(held=HELD)
    assert due(LOCAL, store, set()) == ((LOCAL, C), "")
    assert store.calls == []


def test_host_reserve_takes_it_for_the_manifest_stem_and_says_until_when():
    store = FakeStore(taken={"host": "valhost", "by": "lab", "reason": "S-208", "since": NOW, "until": NOW + 1200})
    code, out, err = run_cmd(cl.cmd_host_reserve, "lab", store, host="valhost", minutes=20.0, reason="S-208")
    assert (code, out, err) == (0, "valhost reserved by lab until 12:20\n", "")
    assert store.calls == [("open", Path("/x/codeteam/run")), ("take", "valhost", 20.0, "lab", "S-208", NOW)]


def test_host_reserve_over_the_cap_is_refused():
    store = FakeStore(take_error="a reservation lasts more than 0 and at most 90 minutes, not 600")
    assert run_cmd(cl.cmd_host_reserve, "lab", store, host="valhost", minutes=600.0, reason="long") == (
        5, "", "host-reserve: a reservation lasts more than 0 and at most 90 minutes, not 600\n")


def test_host_release_by_the_holder():
    store = FakeStore()
    assert run_cmd(cl.cmd_host_release, "lab", store, host="valhost") == (0, "valhost released\n", "")
    assert store.calls[1:] == [("release", "valhost", "lab", NOW)]


def test_host_release_by_another_team_is_refused():
    store = FakeStore(released=False)
    assert run_cmd(cl.cmd_host_release, "acme", store, host="valhost") == (
        5, "", "host-release: valhost is reserved by another team, not acme\n")
    assert store.calls[1:] == [("release", "valhost", "acme", NOW)]


def test_restart_targets_the_new_module():
    assert cl.restart_targets(["share/codeteam_host_reservation.py"]) == {"loops": False, "runners": True,
                                                                          "buildq": False}


if __name__ == "__main__":
    failed = 0
    for name, test in list(globals().items()):
        if name.startswith("test_") and callable(test):
            try:
                test()
                print(f"PASS {name}")
            except Exception as exc:
                failed += 1
                print(f"FAIL {name}: {type(exc).__name__}: {exc!r}")
    print(f"{failed} failed" if failed else "all passed")
    sys.exit(bool(failed))
