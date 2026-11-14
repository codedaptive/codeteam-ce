"""The Branches table in the role text names the branches the team has: a lab that lands with codeteam-land lands on its base itself, so it has no integration or landing."""

import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def codeteam():
    dont_write_bytecode = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        loader = importlib.machinery.SourceFileLoader("codeteam_branch_rows", str(ROOT / "bin" / "codeteam"))
        module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = dont_write_bytecode


def team(*, lab, land):
    return SimpleNamespace(base="main", integration="integration", exchange="exchange", lab=lab,
                           m={"land": {"enabled": True}} if land else {})


def test_a_lab_that_lands_has_one_branch_and_trees_cut_from_it(codeteam):
    rows = codeteam.branch_rows(team(lab=True, land=True))
    assert rows.splitlines()[0].startswith("| `main` | The lab's one branch: work lands on it directly")
    assert "| Work order tree | One work order, cut from `main`, moved by its agent. |" in rows
    assert "`integration` |" not in rows and "`landing` |" not in rows and "Stage 7" not in rows


def test_a_team_on_v54_keeps_its_three_branches(codeteam):
    rows = codeteam.branch_rows(team(lab=False, land=True))
    assert [line.split("|")[1].strip() for line in rows.splitlines()] == [
        "`main`", "`integration`", "`landing`", "Work order tree"]


def test_a_lab_without_landing_keeps_its_lane_rows(codeteam):
    rows = codeteam.branch_rows(team(lab=True, land=False))
    assert "Lanes squash their work onto it" in rows and "Work order tree" not in rows
