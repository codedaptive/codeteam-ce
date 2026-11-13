#!/usr/bin/env -S python3 -u
"""A land stopped by SIGTERM or SIGHUP exits through its finally blocks and restores the signal handler.
Moved from tests/unit/land-v52-sets.py: each case sends this process a real signal and sleeps up to 5 s, so it is an integration test."""
import importlib.machinery
import importlib.util
import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

# Restart markers and stage admissions live beside the queue; keep them out of the checkout.
os.environ["CODETEAM_QUEUE_DIR"] = str(Path(tempfile.mkdtemp(prefix="land-queue-")) / "queue")

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_stopped", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader("cl_stopped", loader)
cl = importlib.util.module_from_spec(spec)
with patch("subprocess.run", return_value=SimpleNamespace(stdout="")):
    loader.exec_module(cl)

# These isolated stage fixtures represent teams that have already moved over.
cl.v54_unmoved = Mock(return_value=False)


def team(cfg=None, env=None):
    obj = Mock()
    obj.cfg = cfg or {}
    obj.m = {"env": env or {}}
    obj.c.side_effect = lambda key, default: obj.cfg.get(key, default)
    obj.zones = {"A": ["a", "shared"], "B": ["b", "shared"]}
    obj.root = Path("/team")
    obj.repo = Path("/repo")
    obj.integration = "integration"
    obj.landing = "landing"
    obj.lab = False
    obj.manifest = Path("/team.toml")
    obj.dir = Path(tempfile.mkdtemp(prefix="land-set-unit-"))
    for name in ("queue", "reviews", "wo"):
        (obj.dir / name).mkdir()
    return obj


class StoppedLand(unittest.TestCase):
    """SIGTERM ends a land as an exit, so its finally blocks restore the set's first tree and save every record
   . The checks are faked; the signal is real, sent to this process."""

    def test_sigterm_mid_check_exits_143_after_the_finally_blocks_and_restores_the_handler(self):
        import signal
        before, ran = signal.getsignal(signal.SIGTERM), []

        def stopped_mid_check(team_, a, names):
            try:
                os.kill(os.getpid(), signal.SIGTERM)
                cl.time.sleep(5)
            finally:
                ran.append("finally")

        args = SimpleNamespace(wo="one", with_=["two"], untested=False)
        with patch.object(cl, "check_and_queue", side_effect=stopped_mid_check), \
                redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit) as ex:
            cl.cmd_land(team(), args)
        self.assertEqual((ex.exception.code, ran), (143, ["finally"]))
        self.assertIn("stopped (SIGTERM)", err.getvalue())
        self.assertIs(signal.getsignal(signal.SIGTERM), before)

    def test_sighup_mid_check_exits_129_after_the_finally_blocks_and_restores_the_handler(self):
        # A land whose session goes away may get SIGHUP; it restores the tree as on SIGTERM.
        import signal
        before, ran = signal.getsignal(signal.SIGHUP), []

        def stopped_mid_check(team_, a, names):
            try:
                os.kill(os.getpid(), signal.SIGHUP)
                cl.time.sleep(5)
            finally:
                ran.append("finally")

        args = SimpleNamespace(wo="one", with_=["two"], untested=False)
        with patch.object(cl, "check_and_queue", side_effect=stopped_mid_check), \
                redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit) as ex:
            cl.cmd_land(team(), args)
        self.assertEqual((ex.exception.code, ran), (129, ["finally"]))
        self.assertIn("stopped (SIGHUP)", err.getvalue())
        self.assertIs(signal.getsignal(signal.SIGHUP), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
