#!/usr/bin/env -S python3 -u
"""A work order's record is never seen half-written, and a reader never dies on one that went away.
save_record writes a temporary file of the writer's own, flushes it to
disk and moves it into place; a write that fails removes its temporary file. save_wo and wo-retire's .retired.json use
it. open_records, clean_idle and Team.wo skip or refuse a record a concurrent retire removed between the listing and
the read. A failing write is simulated by os.fsync raising ENOSPC; a vanished record by read_text raising
FileNotFoundError for it. The unit tests (rule 11); the test of two writers at once is in
tests/integration/land-record-atomic.py."""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
        loader.exec_module(module)
    return module


cl = load("cl_record_atomic", ROOT / "bin" / "codeteam-land")
REAL_READ_TEXT = Path.read_text


class FakeTeam:
    """Only the record methods of codeteam-land's Team, on a scratch folder."""
    wo_file = cl.Team.wo_file
    wo = cl.Team.wo
    save_wo = cl.Team.save_wo

    def __init__(self, d: Path):
        self.dir = self.repo = self.root = d
        (d / "wo").mkdir()

    def c(self, key, default=None):
        return default


def full_disk(fd):
    raise OSError(28, "No space left on device")


def vanishing(name):
    """read_text that finds `name` gone, as if a retire removed it after the listing."""
    def read_text(self, *args, **kwargs):
        if self.name == name:
            raise FileNotFoundError(2, "No such file or directory", str(self))
        return REAL_READ_TEXT(self, *args, **kwargs)
    return read_text


def scratch():
    return Path(tempfile.mkdtemp(prefix="land-record-atomic-"))


def test_a_save_cut_short_leaves_the_old_record_whole_and_no_temporary_file():
    d = scratch()
    try:
        team = FakeTeam(d)
        team.save_wo({"wo": "a", "zone": "cli", "tree": "/t/a"})
        with patch.object(os, "fsync", full_disk):
            try:
                team.save_wo({"wo": "a", "zone": "cli", "tree": "/t/a", "joined": "now"})
            except OSError:
                pass
            else:
                raise AssertionError("the failing write was not exercised")
        assert json.loads(team.wo_file("a").read_text()) == {"wo": "a", "zone": "cli", "tree": "/t/a"}
        assert sorted(p.name for p in (d / "wo").iterdir()) == ["a.json"]
    finally:
        shutil.rmtree(d)


def test_a_save_leaves_only_the_record():
    d = scratch()
    try:
        team = FakeTeam(d)
        team.save_wo({"wo": "a", "zone": "cli"})
        team.save_wo({"wo": "a", "zone": "cli", "joined": "now"})
        assert sorted(p.name for p in (d / "wo").iterdir()) == ["a.json"]
        assert team.wo("a") == {"wo": "a", "zone": "cli", "joined": "now"}
    finally:
        shutil.rmtree(d)


def test_a_save_is_on_disk_before_it_replaces_the_record():
    d = scratch()
    try:
        calls = []
        real_fsync, real_replace = os.fsync, Path.replace
        with patch.object(os, "fsync", lambda fd: (calls.append("fsync"), real_fsync(fd))), \
                patch.object(Path, "replace", lambda self, to: (calls.append("replace"), real_replace(self, to))[1]):
            cl.save_record(d / "r.json", {"a": 1})
        assert calls == ["fsync", "replace"], calls
    finally:
        shutil.rmtree(d)


def test_a_retire_cut_short_leaves_no_torn_retired_record():
    d = scratch()
    try:
        team = FakeTeam(d)
        team.save_wo({"wo": "a", "zone": "cli", "tree": str(d / "gone"), "branch": "wo/cli/a"})
        a = SimpleNamespace(wo="a", force=False, reason=None)
        with patch.object(cl, "entry_path", return_value=None), \
                patch.object(cl, "codegraph_unregister", create=True), \
                patch.object(cl, "git", return_value=SimpleNamespace(stdout="", stderr="", returncode=0)), \
                patch.object(os, "fsync", full_disk):
            try:
                cl.cmd_wo_retire(team, a)
            except OSError:
                pass
        assert sorted(p.name for p in (d / "wo").iterdir()) == ["a.json"]
        assert team.wo("a")["zone"] == "cli"
    finally:
        shutil.rmtree(d)


def test_a_retire_keeps_the_whole_record_as_retired():
    d = scratch()
    try:
        team = FakeTeam(d)
        team.save_wo({"wo": "a", "zone": "cli", "tree": str(d / "gone"), "branch": "wo/cli/a"})
        a = SimpleNamespace(wo="a", force=False, reason="done")
        with patch.object(cl, "entry_path", return_value=None), \
                patch.object(cl, "git", return_value=SimpleNamespace(stdout="", stderr="", returncode=0)):
            cl.cmd_wo_retire(team, a)
        assert sorted(p.name for p in (d / "wo").iterdir()) == ["a.retired.json"]
        kept = json.loads((d / "wo" / "a.retired.json").read_text())
        assert kept["zone"] == "cli" and kept["retired_reason"] == "done" and kept["retired"]
    finally:
        shutil.rmtree(d)


def test_open_records_skip_a_record_gone_since_the_listing_or_one_that_does_not_parse():
    d = scratch()
    try:
        team = FakeTeam(d)
        team.save_wo({"wo": "a", "zone": "cli", "feature": "f"})
        team.save_wo({"wo": "b", "zone": "v2", "feature": "f"})
        (d / "wo" / "c.json").write_text('{"wo": "c", "zo')
        cl.save_record(d / "wo" / "d.retired.json", {"wo": "d", "zone": "zone"})
        with patch.object(Path, "read_text", vanishing("b.json")):
            assert [rec["wo"] for _, rec in cl.open_records(team)] == ["a"]
            assert cl.open_tagged(team, "f") == ["a"]
            assert cl.promotion_coordinators(team, []) == {}
    finally:
        shutil.rmtree(d)


def test_idle_clean_skips_a_record_gone_since_the_listing():
    d = scratch()
    try:
        team = FakeTeam(d)
        team.save_wo({"wo": "b", "zone": "v2", "tree": str(d / "no-tree")})
        with patch.object(Path, "read_text", vanishing("b.json")), patch.object(cl, "process_cwds", return_value=[]):
            cl.clean_idle(team)
    finally:
        shutil.rmtree(d)


def test_a_work_order_gone_since_it_was_named_is_unknown_not_a_crash():
    d = scratch()
    try:
        team = FakeTeam(d)
        team.save_wo({"wo": "b", "zone": "v2"})
        with patch.object(Path, "read_text", vanishing("b.json")):
            try:
                team.wo("b")
            except SystemExit as stop:
                assert stop.code == cl.REFUSED
            else:
                raise AssertionError("no refusal")
    finally:
        shutil.rmtree(d)


if __name__ == "__main__":
    for fn in (test_a_save_cut_short_leaves_the_old_record_whole_and_no_temporary_file, test_a_save_leaves_only_the_record,
               test_a_save_is_on_disk_before_it_replaces_the_record,
               test_a_retire_cut_short_leaves_no_torn_retired_record, test_a_retire_keeps_the_whole_record_as_retired,
               test_open_records_skip_a_record_gone_since_the_listing_or_one_that_does_not_parse,
               test_idle_clean_skips_a_record_gone_since_the_listing,
               test_a_work_order_gone_since_it_was_named_is_unknown_not_a_crash):
        fn()
    print("all passed")
