#!/usr/bin/env python3
"""Unit tests for selecting stale copies of build artifacts."""

import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_stale_copies import stale_copies


class StaleCopiesTests(unittest.TestCase):
    NOW = 1704067200
    CUTOFF = NOW - 86400
    OLD = NOW - 200000
    NEWER = NOW - 100000
    RECENT = NOW - 3600
    A = "0123456789abcdef"
    B = "fedcba9876543210"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.deps = Path(self.temp.name) / "deps"
        self.deps.mkdir()

    def copy(self, hash_, atime, mtime):
        paths = [self.deps / f"libfoo-{hash_}.rlib", self.deps / f"libfoo-{hash_}.rmeta",
                 self.deps / f"foo-{hash_}.d"]
        for path in paths:
            path.write_bytes(b"data")
            os.utime(path, (atime, mtime))
        return paths

    def test_keeps_newest_copy_and_returns_every_entry_of_old_copy(self):
        old = self.copy(self.A, self.OLD, self.OLD)
        newest = self.copy(self.B, self.OLD, self.NEWER)
        result = stale_copies(self.deps, self.CUTOFF)
        self.assertEqual(len(result), 1)
        self.assertCountEqual(result[0], old)
        self.assertTrue(all(path not in result[0] for path in newest))

    def test_recent_atime_on_one_entry_keeps_older_copy(self):
        old = self.copy(self.A, self.OLD, self.OLD)
        self.copy(self.B, self.OLD, self.NEWER)
        os.utime(old[1], (self.RECENT, self.OLD))
        self.assertEqual(stale_copies(self.deps, self.CUTOFF), [])

    def test_recent_mtime_on_non_newest_copy_keeps_it(self):
        self.copy(self.A, self.OLD, self.RECENT)
        self.copy(self.B, self.OLD, self.NOW - 60)
        self.assertEqual(stale_copies(self.deps, self.CUTOFF), [])

    def test_executable_and_library_are_distinct_artifacts(self):
        for name in (f"cli-{self.A}", f"cli-{self.A}.d", f"libcli-{self.B}.rlib"):
            path = self.deps / name
            path.write_bytes(b"x")
            os.utime(path, (self.OLD, self.OLD))
        self.assertEqual(stale_copies(self.deps, self.CUTOFF), [])

    def test_a_crate_named_libc_keeps_its_d_file_with_its_copy(self):
        """The libc crate writes liblibc-<hash>.rlib beside libc-<hash>.d: one copy, removed whole."""
        old = []
        for hash_, mtime in ((self.A, self.OLD), (self.B, self.NEWER)):
            for name in (f"liblibc-{hash_}.rlib", f"liblibc-{hash_}.rmeta", f"libc-{hash_}.d"):
                path = self.deps / name
                path.write_bytes(b"x")
                os.utime(path, (self.OLD, mtime))
                if hash_ == self.A:
                    old.append(path)
        result = stale_copies(self.deps, self.CUTOFF)
        self.assertEqual(len(result), 1)
        self.assertCountEqual(result[0], old)

    def test_unmatched_names_are_not_returned(self):
        old = self.copy(self.A, self.OLD, self.OLD)
        self.copy(self.B, self.OLD, self.NEWER)
        for name in ("notes", "libfoo-nothex.rlib", "foo-0123456789abcde.d"):
            path = self.deps / name
            path.write_bytes(b"x")
            os.utime(path, (self.OLD, self.OLD))
        result = stale_copies(self.deps, self.CUTOFF)
        self.assertEqual(len(result), 1)
        self.assertCountEqual(result[0], old)

    def test_missing_deps_returns_empty(self):
        self.assertEqual(stale_copies(self.deps / "missing", self.CUTOFF), [])

    def test_symlink_and_non_directory_deps_return_empty(self):
        link = self.deps.parent / "link"
        link.symlink_to(self.deps, target_is_directory=True)
        file = self.deps.parent / "file"
        file.write_bytes(b"x")
        self.assertEqual(stale_copies(link, self.CUTOFF), [])
        self.assertEqual(stale_copies(file, self.CUTOFF), [])


if __name__ == "__main__":
    unittest.main()
