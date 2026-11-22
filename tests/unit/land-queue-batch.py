#!/usr/bin/env -S python3 -u
import contextlib
import importlib.machinery
import importlib.util
import inspect
import io
import json
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_queue_batch", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)


def test_queue_entry_default_keeps_legacy_shape():
    assert cl.queue_entry("a", "tip", "base", ["z"], "now") == {
        "wos": ["a"], "wo": "a", "tip": "tip", "base": "base", "zones": ["z"],
        "queued": "now", "state": "waiting", "review": "pending"}


def test_queue_entry_files_marks_integration_owed():
    assert "files" in inspect.signature(cl.queue_entry).parameters
    entry = cl.queue_entry("a", "tip", "base", ["z"], "now", files=["src/a.py"])
    assert entry["integration"] == "owed"
    assert entry["files"] == ["src/a.py"]


def test_legacy_ready_entry_lands_alone_before_owed_entries():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "queue").mkdir()
        team = SimpleNamespace(dir=root)
        owed = root / "queue" / "01.json"
        legacy = root / "queue" / "02.json"
        owed.write_text(json.dumps({"wo": "owed", "review": "land", "integration": "owed"}))
        legacy.write_text(json.dumps({"wo": "old", "review": "land"}))
        with patch.object(cl, "prune_queue"), patch.object(cl, "Lock", return_value=contextlib.nullcontext()), \
                patch.object(cl, "land_entry", return_value=0) as land, \
                patch.object(cl, "queue_batch", create=True) as batch:
            assert cl.advance_queue(team) is True
        assert land.call_args.args == (team, legacy)
        assert not batch.called


def test_all_ready_owed_entries_go_to_batch_outside_lock():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "queue").mkdir()
        team = SimpleNamespace(dir=root)
        records = [("01", "a", "land", False), ("02", "held", "land", True),
                   ("03", "pending", "pending", False), ("04", "b", "land", False)]
        for name, wo, review, hold in records:
            (root / "queue" / f"{name}.json").write_text(json.dumps(
                {"wo": wo, "review": review, "hold": hold, "integration": "owed"}))
        locked = []
        @contextlib.contextmanager
        def lock(*args):
            locked.append(True)
            try:
                yield
            finally:
                locked.pop()
        def batch(*args):
            assert not locked
            return True
        with patch.object(cl, "prune_queue"), patch.object(cl, "Lock", side_effect=lock), \
                patch.object(cl, "land_entry", return_value=0) as land, \
                patch.object(cl, "queue_batch", side_effect=batch, create=True) as queued:
            assert cl.advance_queue(team) is True
        assert not land.called
        assert queued.call_args.args[:2] == (team, [root / "queue" / "01.json", root / "queue" / "04.json"])


def test_stage2_runs_compile_and_units_but_not_integration_steps():
    team = SimpleNamespace(c=lambda key, default: default)
    rec = {"wo": "a", "tree": "tree", "files": ["src/a"]}
    calls = []
    def stages(team, rec, steps, group, **kwargs):
        calls.append((list(steps), group))
        return True
    with patch.object(cl, "duplicate_rulings", return_value=[]), patch.object(cl, "reach", return_value=["z"]), \
            patch.object(cl, "compile_steps", return_value=[("compile z", "compile")]), \
            patch.object(cl, "repo_test_steps", return_value=[("units", "unit")]), \
            patch.object(cl, "zone_steps", return_value=[("tests z", "test")]), \
            patch.object(cl, "stage2_steps", side_effect=stages):
        assert cl.check_integration(team, rec, False) == ["z"]
    assert calls == [([("compile z", "compile")], "integration"), ([("units", "unit")], "unit")]


def queued_set(kinds):
    records = [{"wo": "a", "zone": "A", "tree": "tree-a"},
               {"wo": "b", "zone": "B", "tree": "tree-b"}]
    members = list(zip(records, kinds))
    team = SimpleNamespace(repo="repo", integration="integration", save_wo=Mock(), notify=Mock())
    args = SimpleNamespace(wo="a")
    output = io.StringIO()
    with patch.object(cl, "checked_members", return_value=members), \
            patch.object(cl, "other_member_heads", return_value=[], create=True), \
            patch.object(cl, "out", side_effect=lambda tree, *args: {"repo": "base", "tree-a": "tip-a", "tree-b": "tip-b"}[tree]), \
            patch.object(cl, "merge_checked_base"), patch.object(cl, "own_base", return_value="base"), \
            patch.object(cl, "changed_files", side_effect=lambda tree, base: {"tree-a": ["src/a"], "tree-b": ["src/b"]}[tree]), \
            patch.object(cl, "check_combined_members", return_value=(["A", "B"], ["A", "B"])), \
            patch.object(cl, "slow_tests_flag", return_value=None), patch.object(cl, "now", return_value="now"), \
            patch.object(cl, "stamp_members", return_value="docs-only" if all(kinds) else False), \
            patch.object(cl, "Lock", return_value=contextlib.nullcontext()), \
            patch.object(cl, "queue_stage3", return_value={}) as queue, \
            patch.object(cl, "report_slow_tests"), contextlib.redirect_stdout(output):
        cl.check_and_queue(team, args, ["a", "b"])
    return queue.call_args.args[2], output.getvalue()


def test_building_set_queues_owed_integration_with_all_changed_files():
    entry, output = queued_set([None, None])
    assert entry.get("integration") == "owed"
    assert set(entry["files"]) == {"src/a", "src/b"}
    assert "Stage 2 passed" in output
    assert "integration step owed at landing" in output


def test_docs_only_set_has_no_integration_owed():
    entry, output = queued_set(["docs-only", "docs-only"])
    assert "integration" not in entry
    assert "files" not in entry
    assert "Stage 2 passed" in output
    assert "integration step owed at landing" not in output


if __name__ == "__main__":
    failures = 0
    for name, test in list(globals().items()):
        if name.startswith("test_") and callable(test):
            try:
                test()
                print(f"PASS {name}")
            except Exception:
                failures += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    print(f"{failures} failed")
    sys.exit(bool(failures))
