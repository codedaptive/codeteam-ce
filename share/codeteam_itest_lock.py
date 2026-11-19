"""The lock on the landing tool's one itest tree.

The batch rule batches integration runs into one land/itest checkout. Whoever checks that tree out and runs steps in it
(the Stage 5 recheck runner through `recheck_at`, and queue-run's Stage 2 integration step) holds this lock for that whole span, so no other holder moves the tree
under its running tests.
"""

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

LOCK_FILE = "itest.lock"        # in the team's land/ folder; wo-cut's warm_itest tries the same file


@contextmanager
def itest_lock(folder: Path) -> Iterator[None]:
    """Hold an exclusive flock on folder/LOCK_FILE (created when missing) for the block; closing the file at the
    block's end releases it."""
    with (Path(folder) / LOCK_FILE).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield
