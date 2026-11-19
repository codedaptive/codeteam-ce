"""wo-cut's warm start: a new work order tree is cloned from land/itest's build output when that tree is free.

The lock is tried, never waited for: wo-cut runs inside Claude Code's WorktreeCreate hook, which gives up on a slow
one, and the Stage 5 recheck and queue-run hold the itest lock for a whole integration run. A tree that is not warmed
builds through the caches.
"""

import fcntl
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from codeteam_itest_lock import LOCK_FILE

PREPARED = "codeteam-prepared"


def _git_dir(tree: Path) -> Path:
    return Path(subprocess.run(["git", "-C", str(tree), "rev-parse", "--path-format=absolute", "--git-dir"],
                               capture_output=True, text=True, check=True).stdout.strip())


def warm_itest(team_root: str | Path, dest: str | Path, clone: Callable[[Path, Path], None]) -> bool:
    """clone(land/itest, dest) under the itest lock, with its prepared mark; False, copying nothing, when there is
    no land/itest or another holds the lock."""
    folder = Path(team_root) / "land"
    source = folder / "itest"
    if not source.is_dir():
        return False
    with (folder / LOCK_FILE).open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        clone(source, dest)
        mark = _git_dir(source) / PREPARED
        if mark.exists():           # its prepared folders came with the clone: same lockfile, same state
            shutil.copy(mark, _git_dir(Path(dest)) / PREPARED)
    return True
