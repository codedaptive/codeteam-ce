"""An exclusive file lock whose waiters are served first come, first served (D592).

fcntl.flock alone does not serve waiters in order, so a team could wait hours behind others' repeated suites. Each
waiter leaves a ticket: an empty file named `<arrival time_ns>-<pid>` in the folder `<lock name>.tickets` beside the
lock file; any other name in that folder is ignored and kept. Only the oldest ticket whose process is alive may take
the lock; a dead waiter's ticket is skipped and removed. The holder's ticket stays while it holds the lock and goes
when the block ends.

The flock remains the exclusion: a holder that dies still frees it, and a runner on older code that only flocks can
never run beside one using this lock. Limits: liveness is os.kill(pid, 0), so a dead waiter whose pid is reused by a
live process keeps its ticket, and so its place, until that process ends; and a killed waiter its living parent has
not reaped (a zombie) counts as alive until it is reaped.
"""

import fcntl
import os
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from codeteam_lock_turn import lock_turn

# The folder is shared state on a live machine: a name that is not a ticket (.DS_Store, an editor's swap file) is
# ignored and left in place, never parsed into an error and never removed, since it is not ours. A ticket is exactly
# the name fifo_lock writes: decimal numbers without leading zeros, so the name rebuilt to remove a dead ticket is its
# own, and a pid os.kill accepts (a C int above 0; a larger one raises OverflowError, and 0 means the process group).
_TICKET = re.compile(r"(0|[1-9][0-9]*)-([1-9][0-9]*)")
_PID_MAX = 2**31 - 1


def _ticket(name: str) -> tuple[int, int] | None:
    """(time_ns, pid) if name is a ticket, else None."""
    m = _TICKET.fullmatch(name)
    return (int(m[1]), int(m[2])) if m and int(m[2]) <= _PID_MAX else None


def _alive(pid: int) -> bool:
    """Whether a process with this pid exists; one owned by another user counts as alive."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


@contextmanager
def fifo_lock(lockf: Path, poll: float = 3.0) -> Iterator[None]:
    """Hold an exclusive flock on lockf for the block, taken in ticket order; poll seconds between turns."""
    folder = lockf.parent / (lockf.name + ".tickets")
    folder.mkdir(parents=True, exist_ok=True)
    own = (time.time_ns(), os.getpid())
    ticket = folder / f"{own[0]}-{own[1]}"
    try:
        ticket.touch()
        while True:
            tickets = [t for t in (_ticket(p.name) for p in folder.iterdir()) if t]
            head, dead = lock_turn(tickets, {pid for _, pid in tickets if _alive(pid)})
            for t, pid in dead:
                (folder / f"{t}-{pid}").unlink(missing_ok=True)
            if head == own:
                break
            time.sleep(poll)
        with open(lockf, "a") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            yield
    finally:
        ticket.unlink(missing_ok=True)
