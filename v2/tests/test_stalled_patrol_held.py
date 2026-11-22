"""A held lane's work order is not reported stalled: patrol.stalled_work_orders names a stopped work order, and
leaves it out when its lane is in the held set. v2's integration group (rule 11, integration_module): a real land
record in a temp folder, with git faked."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from codeteam2 import patrol  # noqa: E402
from conftest import integration_module  # noqa: E402

pytestmark = integration_module


class PatrolHeldStalledTest(unittest.TestCase):
    def test_patrolheld_work_order_is_not_stalled(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            land = root / "land"
            (land / "wo").mkdir(parents=True)
            tree = root / "tree"
            tree.mkdir()
            (land / "wo" / "rework.json").write_text(json.dumps({
                "wo": "rework", "zone": "eventlog", "tree": str(tree), "base": "base"}))

            def git(args, **kwargs):
                return SimpleNamespace(stdout="1" if "rev-list" in args else "1000000")

            with patch("subprocess.run", side_effect=git):
                lines = patrol.stalled_work_orders(land, {}, {}, {}, 2_000_000_000.0)
                self.assertEqual(len(lines), 1)
                self.assertIn("eventlog: STALLED WORK ORDER rework", lines[0])
                self.assertEqual(patrol.stalled_work_orders(land, {}, {}, {}, 2_000_000_000.0,
                                                          held=frozenset({"eventlog"})), [])
