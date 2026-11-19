import fcntl
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_itest_lock import itest_lock


def test_lock_is_exclusive_until_context_exits(tmp_path):
    with itest_lock(tmp_path):
        with (tmp_path / "itest.lock").open("r+") as other:
            with pytest.raises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with (tmp_path / "itest.lock").open("r+") as other:
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(other, fcntl.LOCK_UN)
