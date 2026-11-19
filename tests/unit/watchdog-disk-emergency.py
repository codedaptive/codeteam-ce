#!/usr/bin/env python3
"""Unit tests for the watchdog's disk emergency (below 20 GB free, delete Time
Machine's local snapshots, the compile cache's generations other than the newest, and sccache's entries beyond its
cap, and tell the owner each time). Every path is a temp folder and every command a fake: nothing here touches
this machine's snapshots or caches."""

import contextlib
import importlib.machinery
import importlib.util
import io
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[2] / "bin" / "codeteam-watchdog"
GIB = 2 ** 30


def load_watchdog():
    loader = importlib.machinery.SourceFileLoader("watchdog_emergency_under_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    with (patch("sys.dont_write_bytecode", True),
          contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO())):
        loader.exec_module(module)
    return module


class FakeTmutil:
    """tmutil: listlocalsnapshotdates answers `listing`; deletelocalsnapshots fails for the dates in `refuse`."""

    def __init__(self, listing="", refuse=()):
        self.listing, self.refuse, self.calls = listing, set(refuse), []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[1] == "listlocalsnapshotdates":
            return SimpleNamespace(returncode=0, stdout=self.listing, stderr="")
        if argv[2] in self.refuse:
            return SimpleNamespace(returncode=1, stdout="", stderr="Failed to delete local snapshot")
        return SimpleNamespace(returncode=0, stdout="", stderr="")


LISTING = "Snapshot dates for volume group containing disk /:\n2026-11-13-130012\n2026-11-13-120007\n"


class Emergency(unittest.TestCase):
    def setUp(self):
        self.wd = load_watchdog()
        self.notified = []
        self.wd.notify = lambda title, body: self.notified.append(body)
        self.tmp = tempfile.TemporaryDirectory(prefix="disk-emergency-")
        self.root = Path(self.tmp.name)
        self.cache = self.root / "codeteam-compilation-cache" / "builtin"
        self.cache.mkdir(parents=True)
        self.sccache = self.root / "sccache"
        self.sccache.mkdir()
        self.trash = self.root / "trash"
        self.said, self.spawned = [], []

    def tearDown(self):
        self.tmp.cleanup()

    def run_it(self, free, tmutil=None, cap=10 ** 12):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.wd.disk_emergency(free=lambda: free, run=tmutil or FakeTmutil(), cache=self.cache,
                                          sccache=self.sccache, cap=cap, trash=self.trash,
                                          spawn=lambda argv, **kw: self.spawned.append(argv),
                                          say=self.said.append)

    def test_at_or_above_20_gb_nothing_is_looked_at(self):
        tmutil = FakeTmutil(LISTING)
        (self.cache / "v1.53").mkdir()
        (self.cache / "v1.54").mkdir()
        self.assertEqual(self.run_it(20.0, tmutil), [])
        self.assertEqual(tmutil.calls, [])
        self.assertTrue((self.cache / "v1.53").is_dir())
        self.assertEqual(self.said, [])

    def test_below_20_gb_each_local_snapshot_is_deleted_oldest_first_and_the_owner_is_told_once(self):
        tmutil = FakeTmutil(LISTING)
        self.run_it(12.0, tmutil)
        self.assertEqual(tmutil.calls[1:], [["tmutil", "deletelocalsnapshots", "2026-11-13-120007"],
                                            ["tmutil", "deletelocalsnapshots", "2026-11-13-130012"]])
        self.assertEqual(len(self.said), 1)
        self.assertIn("2026-11-13-120007", self.said[0])
        self.assertIn("2026-11-13-130012", self.said[0])
        self.assertIn("12 GB free", self.said[0])

    def test_a_snapshot_that_will_not_go_is_logged_and_noticed_not_posted(self):
        lines = self.run_it(12.0, FakeTmutil(LISTING, refuse={"2026-11-13-120007", "2026-11-13-130012"}))
        self.assertEqual(len(lines), 2)
        self.assertTrue(all("not deleted: Failed to delete local snapshot" in x for x in lines), lines)
        self.assertEqual(self.said, [])
        self.assertEqual(len(self.notified), 1)

    def test_compile_cache_generations_but_the_newest_go_and_nothing_else(self):
        for name in ("v1.9", "v1.10", "v1.53", "v1.54", "notes"):
            (self.cache / name).mkdir()
        (self.cache / "lock").write_text("")
        (self.cache / "v1.validation").write_text("x")
        self.run_it(12.0)
        self.assertEqual(sorted(p.name for p in self.cache.iterdir()), ["lock", "notes", "v1.54", "v1.validation"])
        self.assertEqual(sorted(p.name.split("-", 2)[2] for p in self.trash.iterdir()), ["v1.10", "v1.53", "v1.9"])
        self.assertEqual(self.spawned, [["sh", "-c", f"rm -rf {self.trash}/*"]])
        self.assertIn("v1.9, v1.10, v1.53", self.said[0])

    def test_one_generation_alone_is_the_newest_and_stays(self):
        (self.cache / "v1.54").mkdir()
        self.assertEqual(self.run_it(12.0), [])
        self.assertTrue((self.cache / "v1.54").is_dir())
        self.assertEqual(self.spawned, [])

    def make_sccache(self, n=5, size=100):
        for i in range(n):
            f = self.sccache / f"{i % 2}" / f"entry{i}"
            f.parent.mkdir(exist_ok=True)
            f.write_bytes(b"x" * size)
            os.utime(f, (1000 + i, 1000 + i))       # entry0 is the oldest

    def test_sccache_loses_its_oldest_files_until_it_is_within_its_cap(self):
        self.make_sccache()
        self.run_it(12.0, cap=250)
        left = sorted(p.name for p in self.sccache.rglob("entry*"))
        self.assertEqual(left, ["entry3", "entry4"])
        self.assertIn("removed sccache's 3 oldest files", self.said[0])

    def test_sccache_within_its_cap_is_left_alone(self):
        self.make_sccache()
        self.assertEqual(self.run_it(12.0, cap=500), [])
        self.assertEqual(len(list(self.sccache.rglob("entry*"))), 5)
        self.assertEqual(self.said, [])


class Cap(unittest.TestCase):
    def setUp(self):
        self.wd = load_watchdog()
        self.tmp = tempfile.TemporaryDirectory(prefix="sccache-cap-")
        self.root = Path(self.tmp.name)
        self.teams = self.root / "teams"
        self.teams.mkdir()
        self.config = self.root / "config"

    def tearDown(self):
        self.tmp.cleanup()

    def cap(self):
        return self.wd.sccache_cap(teams=self.teams, workspace=self.root, config=self.config)

    def test_sizes_read_as_sccache_reads_them(self):
        self.assertEqual(self.wd.size_bytes("80G"), 80 * GIB)
        self.assertEqual(self.wd.size_bytes("512M"), 512 * 2 ** 20)
        self.assertEqual(self.wd.size_bytes("1T"), 2 ** 40)
        self.assertEqual(self.wd.size_bytes("1234"), 1234)
        self.assertIsNone(self.wd.size_bytes("lots"))
        self.assertIsNone(self.wd.size_bytes(None))

    def test_the_smallest_cap_a_team_sets_wins_over_the_config_file(self):
        (self.teams / "a.toml").write_text('[env]\nSCCACHE_CACHE_SIZE = "120G"\n')
        (self.teams / "b.toml").write_text('[env]\nSCCACHE_CACHE_SIZE = "80G"\n')
        (self.teams / "c.toml").write_text('product = "c"\n')
        self.config.write_text('[cache.disk]\ndir = "/x"\nsize = 214748364800\n')
        self.assertEqual(self.cap(), 80 * GIB)

    def test_with_no_team_setting_the_config_file_says(self):
        (self.teams / "c.toml").write_text('product = "c"\n')
        self.config.write_text('[cache.disk]\ndir = "/x"\nsize = 214748364800\n')
        self.assertEqual(self.cap(), 200 * GIB)

    def test_with_neither_there_is_no_cap_and_nothing_is_trimmed(self):
        self.assertIsNone(self.cap())


class Order(unittest.TestCase):
    def test_the_emergency_runs_before_the_floor_and_each_part_runs_when_it_fails(self):
        wd = load_watchdog()
        ran = []

        def fail():
            ran.append("emergency")
            raise OSError(28, "No space left on device")

        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            with (patch.object(wd, "sweep_queue", side_effect=lambda: ran.append("queue")),
                  patch.object(wd, "disk_emergency", side_effect=fail),
                  patch.object(wd, "sweep_disk", side_effect=lambda: ran.append("disk")),
                  patch.object(wd, "sweep_stale_targets", side_effect=lambda *a, **k: ran.append("stale")),
                  patch.object(wd, "prune_reused_trees", side_effect=lambda *a, **k: ran.append("prune"), create=True),
                  patch.object(wd, "manifests", return_value=[]),
                  patch.object(wd, "free_gb", return_value=200),
                  patch.dict(os.environ, {"CODETEAM_QUEUE_DIR": str(Path(tmp) / "queue")}),
                  patch.object(wd, "check_teams", side_effect=lambda: ran.append("teams")),
                  contextlib.redirect_stdout(out)):
                wd.check()
        self.assertEqual(ran, ["queue", "emergency", "disk", "stale", "prune", "teams"])
        self.assertIn("disk_emergency failed: OSError", out.getvalue())


if __name__ == "__main__":
    unittest.main()
