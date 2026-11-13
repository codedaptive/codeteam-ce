#!/usr/bin/env -S python3 -u
"""The hourly sweep clears the landing tool's temp folder (<worktree_root>/land/tmp, its TMPDIR): an entry untouched for
LAND_TMP_AGE_HOURS goes, a fresh one or one with a fresh file inside stays, and lock files stay however old
(9,065 test folders, 2.1 GB, that nothing cleared). Files in a temp folder only."""
import contextlib
import importlib.machinery
import importlib.util
import io
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load():
    sys.dont_write_bytecode = True
    loader = importlib.machinery.SourceFileLoader("codeteam_sweep_land_tmp", str(ROOT / "bin" / "codeteam"))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


ct = load()


def age(path, hours):
    old = time.time() - hours * 3600
    for p in [path, *(path.rglob("*") if path.is_dir() else [])]:
        os.utime(p, (old, old), follow_symlinks=False)


def team(d):
    manifest = d / "t.toml"
    manifest.write_text(f'product = "p"\nrepo = "{d / "repo"}"\nbase = "main"\nworktree_root = "{d / "team"}"\n')
    return ct.Team(str(manifest))


def tmp_folder(d):
    tmp = d / "team" / "land" / "tmp"
    tmp.mkdir(parents=True)
    (tmp / "land-fixes-old").mkdir()
    (tmp / "land-fixes-old" / "big").write_text("x" * 100)
    (tmp / "old-file.txt").write_text("x")
    (tmp / "used-inside").mkdir()
    (tmp / "used-inside" / "stale").write_text("x")
    (tmp / "_Users_owner_landing-tree_.build.lock").write_text("")
    for name in ("land-fixes-old", "old-file.txt", "used-inside", "_Users_owner_landing-tree_.build.lock"):
        age(tmp / name, ct.LAND_TMP_AGE_HOURS + 1)
    (tmp / "used-inside" / "fresh").write_text("x")          # written now: the folder is in use
    (tmp / "pytest-of-owner").mkdir()                          # made now
    return tmp


def test_old_entries_go_and_fresh_ones_and_locks_stay():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        tmp = tmp_folder(d)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ct.sweep_land_tmp(team(d), dry_run=False)
        assert sorted(p.name for p in tmp.iterdir()) == ["_Users_owner_landing-tree_.build.lock", "pytest-of-owner",
                                                          "used-inside"], sorted(p.name for p in tmp.iterdir())
        assert "land/tmp: cleared 2 entries untouched for 24 h" in out.getvalue(), out.getvalue()


def test_dry_run_removes_nothing_and_says_what_it_would_clear():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        tmp = tmp_folder(d)
        before = sorted(p.name for p in tmp.iterdir())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ct.sweep_land_tmp(team(d), dry_run=True)
        assert sorted(p.name for p in tmp.iterdir()) == before
        assert "land/tmp: would clear 2 entries" in out.getvalue(), out.getvalue()


def test_a_team_without_land_tmp_is_left_alone():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ct.sweep_land_tmp(team(d), dry_run=False)
        assert out.getvalue() == "" and not (d / "team" / "land").exists()


if __name__ == "__main__":
    failed = 0
    for test in [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]:
        try:
            test()
            print(f"  PASS {test.__name__}")
        except (Exception, SystemExit) as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{failed} failed" if failed else "all passed")
    sys.exit(1 if failed else 0)
