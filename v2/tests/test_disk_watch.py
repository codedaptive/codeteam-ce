"""The loop warns the orchestrator, and the owner through herdr, when the machine's disk runs low: once per level on the way
down, again only after it recovers (2026-11-11: the disk filled twice and stopped every lane)."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2 import patrol  # noqa: E402
from codeteam2.scheduler import Runtime  # noqa: E402

M = "/teams/x.toml"


class DiskWarningTest(unittest.TestCase):
    def test_plenty_of_space_says_nothing(self):
        self.assertEqual(patrol.disk_warning(120, None, M), (None, None))

    def test_below_the_first_level_warns_once(self):
        warned, text = patrol.disk_warning(45, None, M)
        self.assertEqual(warned, 50)
        self.assertIn("DISK LOW: 45 GiB free", text)
        self.assertIn(f"codeteam sweep {M}", text)
        self.assertIn("Time Machine's hourly snapshot holds every deleted file", text)
        self.assertEqual(patrol.disk_warning(44, warned, M), (50, None))

    def test_the_next_level_down_warns_again(self):
        warned, text = patrol.disk_warning(15, 50, M)
        self.assertEqual(warned, 20)
        self.assertIn("below 20 GiB", text)

    def test_between_the_levels_and_rearm_keeps_quiet(self):
        self.assertEqual(patrol.disk_warning(60, 50, M), (50, None))

    def test_recovery_rearms_only_after_two_hours_above(self):
        # Time Machine's hourly snapshot swings free space above 80 GiB and back every hour.
        self.assertEqual(patrol.disk_warning(90, 20, M), (20, None))
        self.assertEqual(patrol.disk_warning(90, 20, M, above_s=7199), (20, None))
        self.assertEqual(patrol.disk_warning(90, 20, M, above_s=7200), (None, None))
        self.assertEqual(patrol.disk_warning(40, None, M)[0], 50)


class DiskWatchTest(unittest.TestCase):
    def runtime(self):
        team = SimpleNamespace(t=SimpleNamespace(root=Path("/"), orc_name=lambda: "Orc-X", manifest=M), product="x")
        return SimpleNamespace(team=team, store=Mock(), herdr=Mock(), log=Mock())

    def test_low_disk_wakes_the_orchestrator_and_tells_herdr(self):
        rt, st = self.runtime(), {}
        with patch.object(patrol, "free_gib", return_value=30.0):
            Runtime.disk_watch(rt, st, 1000.0)
        rt.store.add.assert_called_once()
        args, kwargs = rt.store.add.call_args
        self.assertEqual(args[:5], ("general", "codeteam", "REQUEST", "Orc-X", "orc"))
        self.assertIn("DISK LOW", args[5])
        self.assertFalse(kwargs.get("ride"))
        rt.herdr.notify.assert_called_once()
        self.assertEqual(st["_disk"]["warned"], 50)

    def test_checked_once_a_minute_and_told_once(self):
        rt, st = self.runtime(), {}
        with patch.object(patrol, "free_gib", return_value=30.0) as free:
            Runtime.disk_watch(rt, st, 1000.0)
            Runtime.disk_watch(rt, st, 1030.0)
            Runtime.disk_watch(rt, st, 1061.0)
        self.assertEqual(free.call_count, 2)
        rt.store.add.assert_called_once()

    def test_an_hourly_swing_above_the_rearm_level_is_one_episode(self):
        # 2026-11-13: one team was told at 18, 35, 47, 19 and 49 GiB between 08:15 and 12:01, each
        # after a short climb above 80 GiB. Now a climb counts only once it has lasted 2 h.
        rt, st = self.runtime(), {}
        frees = [30.0, 90.0, 35.0, 90.0, 18.0, 90.0, 90.0, 90.0, 40.0]
        times = [0, 1800, 3600, 5400, 7200, 9000, 12600, 16200, 18000]
        with patch.object(patrol, "free_gib", side_effect=frees):
            for t in times:
                Runtime.disk_watch(rt, st, 1000.0 + t)
        said = [call.args[5] for call in rt.store.add.call_args_list]
        self.assertEqual([text.split(",")[0] for text in said],
                         ["DISK LOW: 30 GiB free on this machine's data volume", "DISK LOW: 18 GiB free on this "
                          "machine's data volume", "DISK LOW: 40 GiB free on this machine's data volume"])
        self.assertNotIn("above_since", st["_disk"])

    def test_zero_turns_it_off(self):
        rt, st = self.runtime(), {}
        rt.team.disk_check_s = 0
        with patch.object(patrol, "free_gib", return_value=5.0) as free:
            Runtime.disk_watch(rt, st, 1000.0)
        free.assert_not_called()

    def test_an_unreadable_volume_is_logged_not_raised(self):
        rt, st = self.runtime(), {}
        with patch.object(patrol, "free_gib", side_effect=OSError("gone")):
            Runtime.disk_watch(rt, st, 1000.0)
        rt.store.add.assert_not_called()
        rt.log.assert_called_once()


if __name__ == "__main__":
    unittest.main()
