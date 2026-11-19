"""Run one Stage 5 recheck, or queue-run's Stage 2 integration step, in the itest tree under its lock.

The batch rule batches integration runs into the one land/itest checkout; the recheck runner and queue-run's batch hold its
lock (codeteam_itest_lock) so no other holder moves that tree under its running steps. The checkout and the steps run
inside the lock; everything after them (findings, the slow-tests report, completion, landing) takes the landing
tool's other locks, so this lock is released first and never held while waiting for those.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path


def recheck_at(lock: AbstractContextManager, checkout: Callable[[], Path], run: Callable[[Path], object],
               failure: type[Exception], failed: Callable[[Exception], object]) -> object:
    """Inside lock: run(checkout()); when checkout raises failure, failed(that exception) instead."""
    with lock:
        try:
            tree = checkout()
        except failure as ex:
            return failed(ex)
        return run(tree)
