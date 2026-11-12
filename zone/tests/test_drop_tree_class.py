import contextlib
import importlib.machinery
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def load_with_tree_class(tmp_path, monkeypatch):
    gitdir = tmp_path / "gitdir"
    gitdir.mkdir()
    (gitdir / "codeteam-class").write_text("pre\n")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    for name in ("CLASS", "CODETEAM_WARMING", "CODETEAM_SESSION", "CODETEAM_JOBS_PER_SLOT"):
        monkeypatch.delenv(name, raising=False)

    def fake_run(args, **kwargs):
        if args[:2] == ["git", "rev-parse"] and "--git-dir" in args:
            return SimpleNamespace(returncode=0, stdout=f"{gitdir}\n")
        if args[:2] == ["git", "rev-parse"] and "--show-toplevel" in args:
            return SimpleNamespace(returncode=0, stdout=f"{worktree}\n")
        return SimpleNamespace(returncode=1, stdout="")

    def load(name, filename):
        loader = importlib.machinery.SourceFileLoader(name, str(ROOT / "bin" / filename))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        monkeypatch.setattr(module.subprocess, "run", fake_run)
        return module

    return load


def test_submit_dev_ignores_tree_class(load_with_tree_class):
    zone_tool = load_with_tree_class("zone_tool_drop_tree_class_dev", "zone-tool")

    assert zone_tool.parse_submit(["--class", "dev", "--", "true"])["class"] == "dev"


def test_submit_full_ignores_tree_class(load_with_tree_class):
    zone_tool = load_with_tree_class("zone_tool_drop_tree_class_full", "zone-tool")

    assert zone_tool.parse_submit(["--class", "full", "--", "true"])["class"] == "full"


def test_slot_job_dev_ignores_tree_class(load_with_tree_class, tmp_path, monkeypatch):
    slot = load_with_tree_class("codeteam_slot_drop_tree_class", "codeteam-slot")
    monkeypatch.setattr(slot, "queue_lock", lambda q: contextlib.nullcontext())

    job_file = slot.write_job(tmp_path / "queue", "cargo", ["check"])

    assert json.loads(job_file.read_text())["class"] == "dev"
