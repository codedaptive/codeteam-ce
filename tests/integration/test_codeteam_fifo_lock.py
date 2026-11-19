"""share/codeteam_fifo_lock.py and run_land_check's local tier with real processes on a temp lock (D592): waiters take
the lock in arrival order, a killed waiter's ticket is removed and does not block the rest, a plain-flock holder (older
code) and a ticket holder exclude each other, a file in the tickets folder that is not a ticket is ignored and kept,
and an error inside the hold removes the ticket. Real processes, flock and files are not pure, and the subject is
their interplay, so these are zone integration tests (rule 11); the turn rule itself is unit-tested in
tests/unit/test_codeteam_lock_turn.py. Skipped unless CODETEAM_TEST_GROUP=integration."""
import fcntl
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("CODETEAM_TEST_GROUP", "unit") != "integration",
                                reason="integration group only; run with CODETEAM_TEST_GROUP=integration")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))

ROOT = Path(__file__).resolve().parents[2]
SHARE = ROOT / "share"
LAND = ROOT / "bin" / "codeteam-land"

LAND_WAITER = r'''
import functools
import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

land_path, root, name = sys.argv[1:]
loader = importlib.machinery.SourceFileLoader("land_fifo_test", land_path)
module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch("subprocess.run", return_value=SimpleNamespace(stdout="", stderr="", returncode=0)):
    loader.exec_module(module)
module.HERE = Path(root) / "bin"
module.hang_settings = lambda team: {}
module.team_env = lambda team, group=None: {}
module.toolchain_cmd = lambda tier: ""
module.toolchain_fp = lambda tier: "fingerprint"
module.kinds_by_name = lambda env: False
if hasattr(module, "fifo_lock"):
    from codeteam_fifo_lock import fifo_lock
    module.fifo_lock = functools.partial(fifo_lock, poll=0.05)
def suite(*args, **kwargs):
    with (Path(root) / "order").open("a") as order:
        order.write(name + "\n")
    return SimpleNamespace(stdout='{"hash":"abc","result":"pass"}\n', stderr="", returncode=0)
module.subprocess.run = suite
team = SimpleNamespace(zones={}, cfg={}, m={"env": {}})
result = module.run_land_check(team, {"local": True, "path": root, "suite": "test"}, "abc", "validation")
assert result == {"hash": "abc", "result": "pass"}, result
'''

DIRECT_WAITER = r'''
import sys
import time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from codeteam_fifo_lock import fifo_lock
lock, order, name, go = map(Path, sys.argv[2:])
with fifo_lock(lock, poll=0.05):
    with order.open("a") as file:
        file.write(str(name) + "\n")
    if str(go) != "-":
        while not go.exists():
            time.sleep(0.05)
'''


def wait_for(predicate, message, timeout=30):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, message
        time.sleep(0.05)


def ticket_for(folder, process, timeout=30):
    def found():
        return folder.exists() and any(p.name.endswith(f"-{process.pid}") for p in folder.iterdir())
    wait_for(found, f"ticket for waiter pid {process.pid} did not appear in {folder}", timeout)
    return next(p for p in folder.iterdir() if p.name.endswith(f"-{process.pid}"))


@contextmanager
def plain_lock(lock):
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a") as file:
        fcntl.flock(file, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(file, fcntl.LOCK_UN)


@pytest.fixture
def children():
    processes = []
    yield processes
    for process in processes:
        if process.poll() is None:
            process.kill()
        process.wait()


def start(children, script, *args):
    process = subprocess.Popen([sys.executable, "-c", script, *(str(arg) for arg in args)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    children.append(process)
    return process


def finish(process):
    stdout, stderr = process.communicate(timeout=30)
    assert process.returncode == 0, f"child failed: stdout={stdout!r}, stderr={stderr!r}"


def test_local_land_check_serves_queued_waiters_in_arrival_order(tmp_path, children):
    (tmp_path / "bin").mkdir()
    lock = tmp_path / "run" / "validation-local.lock"
    tickets = lock.parent / (lock.name + ".tickets")
    with plain_lock(lock):
        for name in ("1", "2", "3"):
            child = start(children, LAND_WAITER, LAND, tmp_path, name)
            ticket_for(tickets, child, timeout=10)
    for child in children:
        finish(child)
    assert (tmp_path / "order").read_text().splitlines() == ["1", "2", "3"]
    assert list(tickets.iterdir()) == []


def test_killed_waiter_is_removed_and_the_next_waiter_runs(tmp_path, children):
    lock = tmp_path / "lock"
    tickets = tmp_path / "lock.tickets"
    order = tmp_path / "order"
    with plain_lock(lock):
        for name in ("A", "B", "C"):
            child = start(children, DIRECT_WAITER, SHARE, lock, order, name, "-")
            ticket_for(tickets, child)
        dead_ticket = ticket_for(tickets, children[1])
        children[1].kill()
        children[1].wait()
    finish(children[0])
    finish(children[2])
    assert order.read_text().splitlines() == ["A", "C"]
    assert not dead_ticket.exists()
    assert list(tickets.iterdir()) == []


def test_old_plain_flock_holder_excludes_new_waiter(tmp_path, children):
    lock = tmp_path / "lock"
    tickets = tmp_path / "lock.tickets"
    order = tmp_path / "order"
    with plain_lock(lock):
        child = start(children, DIRECT_WAITER, SHARE, lock, order, "waiter", "-")
        ticket_for(tickets, child)
        with order.open("a") as file:
            file.write("released\n")
    finish(child)
    assert order.read_text().splitlines() == ["released", "waiter"]
    assert list(tickets.iterdir()) == []


def test_new_holder_excludes_old_plain_flock_and_keeps_its_ticket(tmp_path, children):
    lock = tmp_path / "lock"
    tickets = tmp_path / "lock.tickets"
    order = tmp_path / "order"
    go = tmp_path / "go"
    child = start(children, DIRECT_WAITER, SHARE, lock, order, "holder", go)
    ticket = ticket_for(tickets, child)
    wait_for(order.exists, "FIFO holder did not enter its critical section")
    assert ticket.exists()
    with lock.open("a") as file:
        with pytest.raises(BlockingIOError):
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    go.touch()
    finish(child)
    assert not ticket.exists()


def test_foreign_files_in_tickets_folder_are_ignored_and_kept(tmp_path, children):
    lock = tmp_path / "lock"
    tickets = tmp_path / "lock.tickets"
    order = tmp_path / "order"
    tickets.mkdir()
    # Two names are not ticket-shaped (.DS_Store, abc-123). The rest look like tickets at time 1 (older than any real
    # one) but are not: four carry this test's own live pid behind a suffix or a leading zero, 1-0 carries pid 0
    # (which os.kill accepts as the process group), and two carry a pid os.kill rejects with OverflowError. A parse that
    # took any of them as a ticket would make the waiter wait behind it forever or raise.
    live = os.getpid()
    foreign = [".DS_Store", "abc-123", f"1-{live}.swp", f"1-{live}-3", f"01-{live}", f"1-0{live}", "1-0",
               f"1-{2**31}", f"1-{2**40}"]
    for name in foreign:
        (tickets / name).touch()
    finish(start(children, DIRECT_WAITER, SHARE, lock, order, "waiter", "-"))
    assert order.read_text().splitlines() == ["waiter"]
    assert sorted(p.name for p in tickets.iterdir()) == sorted(foreign)


def test_exception_in_critical_section_removes_ticket(tmp_path):
    from codeteam_fifo_lock import fifo_lock

    lock = tmp_path / "lock"
    tickets = tmp_path / "lock.tickets"
    with pytest.raises(ValueError, match="inside"):
        with fifo_lock(lock, poll=0.05):
            assert len(list(tickets.iterdir())) == 1
            raise ValueError("inside")
    assert list(tickets.iterdir()) == []
