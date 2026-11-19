"""_lead_paths finds a branch flow v5 work order tree, <root>/wo/<lane>/<wo>, from the id a ledger row names: the work
order's name as written or a bare agent id. Patrol's SERIAL said '0 lead running' for
lab research's two live leads while their rows named no path codeteam could find. A unit test: a temp folder holds the
trees, and the Team is a stand-in with root, repo and lane_dir.
"""

import importlib.machinery
import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def codeteam():
    environment = os.environ.copy()
    dont_write_bytecode = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        for name in list(os.environ):
            if name.startswith("CT_"):
                os.environ.pop(name)
        loader = importlib.machinery.SourceFileLoader("codeteam_lead_paths", str(ROOT / "bin" / "codeteam"))
        module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = dont_write_bytecode
        os.environ.clear()
        os.environ.update(environment)


def team(tmp_path, root=True):
    return SimpleNamespace(root=tmp_path / "team" if root else None, repo=tmp_path / "repo",
                           lane_dir=lambda n: tmp_path / "team" / "workcrews" / n)


def tree(tmp_path, *parts):
    p = tmp_path.joinpath(*parts)
    p.mkdir(parents=True)
    return p


def test_bare_agent_id_finds_the_lanes_work_order_tree(codeteam, tmp_path):
    wo = tree(tmp_path, "team", "wo", "research", "agent-a53a39d9294aa4b25")
    assert codeteam._lead_paths(team(tmp_path), "research", ["a53a39d9294aa4b25"]) == [wo]
    assert codeteam._lead_paths(team(tmp_path), "research", ["agent-a53a39d9294aa4b25"]) == [wo]


def test_work_order_name_finds_its_tree(codeteam, tmp_path):
    wo = tree(tmp_path, "team", "wo", "research", "ort-gpu-placement")
    assert codeteam._lead_paths(team(tmp_path), "research", ["ort-gpu-placement"]) == [wo]


def test_another_lanes_work_order_is_not_this_lanes_lead(codeteam, tmp_path):
    tree(tmp_path, "team", "wo", "training", "agent-a53a39d9294aa4b25")
    assert codeteam._lead_paths(team(tmp_path), "research", ["agent-a53a39d9294aa4b25"]) == []


def test_requests_folder_comes_before_the_work_order_tree(codeteam, tmp_path):
    req = tree(tmp_path, "team", "workcrews", "research", "requests", "agent-x1")
    tree(tmp_path, "team", "wo", "research", "agent-x1")
    assert codeteam._lead_paths(team(tmp_path), "research", ["x1"]) == [req]


def test_a_full_path_and_the_store_still_resolve(codeteam, tmp_path):
    full = tree(tmp_path, "elsewhere", "agent-p")
    store = tree(tmp_path, "repo", ".claude", "worktrees", "agent-s")
    assert codeteam._lead_paths(team(tmp_path), "research", [str(full), "s"]) == [full, store]


def test_a_team_without_root_skips_the_work_order_lookup(codeteam, tmp_path):
    tree(tmp_path, "team", "wo", "research", "agent-z")
    assert codeteam._lead_paths(team(tmp_path, root=False), "research", ["z"]) == []
