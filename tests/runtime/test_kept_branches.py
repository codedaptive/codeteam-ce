"""Check kept branches and branch leftovers, with git calls faked."""

import importlib.machinery
import importlib.util
import os
import sys
import types
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
        if "herdr" in os.environ.get("SSH_AUTH_SOCK", ""):
            os.environ.pop("SSH_AUTH_SOCK")
        for name in list(os.environ):
            if name.startswith("CT_"):
                os.environ.pop(name)
        loader = importlib.machinery.SourceFileLoader("codeteam", str(ROOT / "bin" / "codeteam"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = dont_write_bytecode
        os.environ.clear()
        os.environ.update(environment)


class FakeTeam:
    def __init__(self, manifest, *, lab=False):
        self.base = "main"
        self.exchange = "exchange"
        self.integration = "integration"
        self.lab = lab
        self.prefix = "lane/"
        self.product = "product"
        self.m = manifest
        self.repo = Path("/fake/repo")


LANES = {"lanes": {"cli": {}, "docs": {}, "external": {"ref": "other/main"}}}


def test_keeps_default_landing_branch(codeteam):
    team = FakeTeam({"branch_keep": ["stable/1"], "land": {"enabled": True}})

    assert codeteam.kept_branches(team, LANES) == {
        "main", "stable/1", "exchange", "integration", "lane/cli", "lane/docs", "landing"
    }


def test_keeps_custom_landing_branch(codeteam):
    team = FakeTeam({"branch_keep": ["stable/1"], "land": {"enabled": True, "landing": "land/main"}})

    assert codeteam.kept_branches(team, LANES) == {
        "main", "stable/1", "exchange", "integration", "lane/cli", "lane/docs", "land/main"
    }


def test_lab_landing_team_keeps_existing_branches_only(codeteam):
    team = FakeTeam({"branch_keep": ["stable/1"], "land": {"enabled": True, "landing": "land/main"}}, lab=True)

    assert codeteam.kept_branches(team, LANES) == {"main", "stable/1", "lane/cli", "lane/docs"}


def test_team_without_land_keeps_existing_branches_only(codeteam):
    team = FakeTeam({"branch_keep": ["stable/1"]})

    assert codeteam.kept_branches(team, LANES) == {
        "main", "stable/1", "exchange", "integration", "lane/cli", "lane/docs"
    }


def test_disabled_landing_keeps_existing_branches_only(codeteam):
    team = FakeTeam({"branch_keep": ["stable/1"], "land": {"enabled": False, "landing": "land/main"}})

    assert codeteam.kept_branches(team, LANES) == {
        "main", "stable/1", "exchange", "integration", "lane/cli", "lane/docs"
    }


@pytest.mark.parametrize("extra_index", [0, 1], ids=["local", "remote"])
def test_branch_leftovers_excludes_landing_but_reports_stray(codeteam, monkeypatch, extra_index):
    team = FakeTeam({"land": {"enabled": True, "landing": "land/main"}})

    def fake_run(args, *, capture_output, text):
        assert args[:3] == ["git", "-C", "/fake/repo"]
        assert capture_output is True and text is True
        outputs = {
            ("worktree", "list", "--porcelain"): "worktree /fake/repo\nbranch refs/heads/main\n",
            ("for-each-ref", "--format=%(objectname) %(refname:short)", "refs/heads"):
                "aaa main\nbbb land/main\nccc scratch/x\n",
            ("ls-remote", "--heads", "origin"):
                "aaa\trefs/heads/main\nbbb\trefs/heads/land/main\nccc\trefs/heads/scratch/x\n",
        }
        command = tuple(args[3:])
        if command not in outputs:
            pytest.fail(f"unexpected git command: {command}")
        return SimpleNamespace(stdout=outputs[command])

    monkeypatch.setattr(codeteam.subprocess, "run", fake_run)

    result = codeteam.branch_leftovers(team, LANES)
    assert result[extra_index] == ["scratch/x"]


@pytest.mark.parametrize("v55,jj_repo", [(True, False), (False, True), (False, False)], ids=["v55", "jj-repo", "v54"])
def test_branch_leftovers_leaves_a_v55_teams_zone_bookmarks_here_and_reports_them_on_github(codeteam, monkeypatch,
                                                                                          tmp_path, v55, jj_repo):
    # A v5.5 team once pushed two zone/* bookmarks on the patrol's word, and jj made the zones'
    # squashes immutable. On a v5.5 team (the manifest's flag, or a colocated jj repository) a local zone/* is the
    # zone's jj bookmark: not outside the rule, not unmirrored.
    team = FakeTeam({"land": {"enabled": True, "v55": v55}})
    team.repo = tmp_path
    if jj_repo:
        (tmp_path / ".jj").mkdir()
    v55 = v55 or jj_repo

    def fake_run(args, *, capture_output, text):
        outputs = {
            ("worktree", "list", "--porcelain"): f"worktree {tmp_path}\n",
            ("for-each-ref", "--format=%(objectname) %(refname:short)", "refs/heads"):
                "aaa main\nbbb zone/gitio\nccc zone/orc\nddd scratch/x\n",
            ("ls-remote", "--heads", "origin"): "aaa\trefs/heads/main\nbbb\trefs/heads/zone/gitio\n",
        }
        return SimpleNamespace(stdout=outputs[tuple(args[3:])])

    monkeypatch.setattr(codeteam.subprocess, "run", fake_run)

    here, github, unmirrored, *_ = codeteam.branch_leftovers(team, LANES)
    assert here == (["scratch/x"] if v55 else ["scratch/x", "zone/gitio", "zone/orc"])
    assert github == ["zone/gitio"]
    assert "zone/gitio" not in unmirrored and "zone/orc" not in unmirrored



def test_branch_leftovers_counts_what_detached_wo_branches_gives_as_checked_out(codeteam, monkeypatch, tmp_path):
    # Branch_leftovers hands the team's land/wo folder and git's worktree lines to
    # detached_wo_branches (faked here; share/codeteam_detached_wo_branches.py has its own tests, and
    # tests/integration/test_kept_branches_detached.py runs the two together) and counts what it gives as checked out.
    team = FakeTeam({"land": {"enabled": True}})
    team.root = tmp_path
    porcelain = ["worktree /fake/repo", "branch refs/heads/main", f"worktree {tmp_path}/wo/z/w1", "HEAD aaa", "detached"]
    calls = []
    fake = types.ModuleType("codeteam_detached_wo_branches")
    fake.detached_wo_branches = lambda wo_dir, lines: calls.append((wo_dir, list(lines))) or {"wo/z/w1"}
    monkeypatch.setitem(sys.modules, "codeteam_detached_wo_branches", fake)

    def fake_run(args, *, capture_output, text):
        outputs = {
            ("worktree", "list", "--porcelain"): "\n".join(porcelain) + "\n",
            ("for-each-ref", "--format=%(objectname) %(refname:short)", "refs/heads"):
                "aaa main\nbbb wo/z/w1\nccc wo/z/w2\n",
            ("ls-remote", "--heads", "origin"): "aaa\trefs/heads/main\nbbb\trefs/heads/wo/z/w1\n",
        }
        return SimpleNamespace(stdout=outputs[tuple(args[3:])])

    monkeypatch.setattr(codeteam.subprocess, "run", fake_run)

    here, github, unmirrored, *_ = codeteam.branch_leftovers(team, LANES)
    assert calls == [(tmp_path / "land" / "wo", porcelain)]
    assert here == ["wo/z/w2"]
    assert github == []
    assert "wo/z/w1" not in unmirrored
