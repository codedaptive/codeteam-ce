#!/usr/bin/env python3
"""codeteam-land's Lock closes its lock file when the block ends, also when the block raises (Orc-Codeteam-jj #4419,
D500: __exit__ only unlocked, so every `with Lock(team):` left an open file, one per pass of queue-run's loop). A unit
test (rule 11): the team is a fake whose folder is a temp folder; flock is real on that one file."""
import fcntl
import importlib.machinery
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

HOME = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl", str(HOME / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader("cl", loader)
cl = importlib.util.module_from_spec(spec)
loader.exec_module(cl)


def free(path: Path) -> bool:
    """True when another open file can take the lock at once."""
    with open(path, "w") as other:
        try:
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        fcntl.flock(other, fcntl.LOCK_UN)
        return True


class LockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.team = SimpleNamespace(dir=Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_block_holds_the_lock_and_its_end_closes_the_file_and_frees_the_lock(self):
        with cl.Lock(self.team) as held:
            self.assertFalse(free(self.team.dir / "lock"))
        self.assertTrue(held.f.closed)
        self.assertTrue(free(self.team.dir / "lock"))

    def test_a_block_that_raises_still_closes_the_file_and_frees_the_lock(self):
        with self.assertRaises(RuntimeError):
            with cl.Lock(self.team) as held:
                raise RuntimeError("boom")
        self.assertTrue(held.f.closed)
        self.assertTrue(free(self.team.dir / "lock"))


if __name__ == "__main__":
    result = unittest.main(exit=False).result
    sys.exit(0 if result.wasSuccessful() else 1)
