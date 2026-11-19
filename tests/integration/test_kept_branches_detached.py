"""branch_leftovers (bin/codeteam) with share/codeteam_detached_wo_branches.py for real: an open work order whose tree
the landing tool has detached for a set's check is work in progress, read from real record files; git is faked.
It runs two files together, so it is a zone integration test; the unit tests of each are
tests/runtime/test_kept_branches.py and tests/unit/detached-wo-branches.py. Skipped unless
CODETEAM_TEST_GROUP=integration."""

import importlib.machinery
import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("CODETEAM_TEST_GROUP", "unit") != "integration",
                                reason="integration group only; run with CODETEAM_TEST_GROUP=integration")

ROOT = Path(__file__).resolve().parents[2]
LANES = {"lanes": {"cli": {}}}


@pytest.fixture(scope="module")
def codeteam():
    environment = os.environ.copy()
    dont_write_bytecode = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
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
    def __init__(self, manifest, root):
        self.base, self.exchange, self.integration, self.lab = "main", "exchange", "integration", False
        self.prefix, self.product, self.m, self.root = "lane/", "product", manifest, root
        self.repo = Path("/fake/repo")


def test_branch_leftovers_counts_an_open_work_orders_detached_tree_as_checked_out(codeteam, monkeypatch, tmp_path):
    # a landing set's check detaches its first member's tree for the whole of Stage 2, and the
    # audit flagged that open work order's branch on every patrol. A landed work order's branch is still reported.
    team = FakeTeam({"land": {"enabled": True}}, tmp_path)
    wo = tmp_path / "land" / "wo"
    wo.mkdir(parents=True)
    for name in ("w1", "w2"):
        (wo / f"{name}.json").write_text(f'{{"tree": "{tmp_path}/wo/z/{name}", "branch": "wo/z/{name}"}}')
    (wo / "w2.landed.json").write_text("{}")

    def fake_run(args, *, capture_output, text):
        outputs = {
            ("worktree", "list", "--porcelain"): (f"worktree /fake/repo\nbranch refs/heads/main\n\n"
                                                  f"worktree {tmp_path}/wo/z/w1\nHEAD aaa\ndetached\n\n"
                                                  f"worktree {tmp_path}/wo/z/w2\nHEAD bbb\ndetached\n"),
            ("for-each-ref", "--format=%(objectname) %(refname:short)", "refs/heads"):
                "aaa main\nbbb wo/z/w1\nccc wo/z/w2\n",
            ("ls-remote", "--heads", "origin"): "aaa\trefs/heads/main\nbbb\trefs/heads/wo/z/w1\n",
        }
        return SimpleNamespace(stdout=outputs[tuple(args[3:])])

    monkeypatch.setattr(codeteam.subprocess, "run", fake_run)

    here, github, unmirrored, *_ = codeteam.branch_leftovers(team, LANES)
    assert here == ["wo/z/w2"]
    assert github == []
    assert "wo/z/w1" not in unmirrored
