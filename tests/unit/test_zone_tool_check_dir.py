"""zone-tool's type-check: the DIR it gets when the caller names none, and one cached result per scope
.

A product had no `make check`, and could not add one: zone-tool handed it DIR=. for a plain `make zone-check` and for every
suite key, so the check could only do nothing, refuse every suite, or build the whole repo. Now a call with no DIR
checks the lane's zone (CODETEAM_ZONE), and each scope keeps its own clean result for the tree, so moving between a
DIR and the zone does not build again.
"""

import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def zt():
    dont_write_bytecode = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        loader = importlib.machinery.SourceFileLoader("zone_tool_check_dir", str(ROOT / "bin" / "zone-tool"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = dont_write_bytecode


@pytest.fixture
def env(monkeypatch):
    for name in ("CODETEAM_ZONE", "CODETEAM_TEST_GROUP", "GROUP", "ZONE_CHECK", "CODETEAM_OWNS",
                 "CODETEAM_BUILDQ_TICKET", "CODETEAM_LANDING"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def checked_dirs(zt, env):
    """Patch run_check and the guard file: the DIRs run_check was handed, in order."""
    dirs = []
    env.setattr(zt, "run_check", lambda root, d, tree_hash, g: (dirs.append(d), (True, [], "check"))[1])
    env.setattr(zt, "_guards_load", lambda root: {"checks": {}, "whole": {}, "grants": {}, "log": []})
    env.setattr(zt, "_guards_save", lambda root, g: None)
    return dirs


@pytest.mark.parametrize("zone, expect", [("Packages/WidgetVaultKit/", "Packages/WidgetVaultKit"), (".", "."), ("", ".")])
def test_a_key_with_no_dir_checks_the_lanes_zone(zt, env, tmp_path, zone, expect):
    """The zone suite (no key) and a product's own suite key name no DIR: the check gets the lane's zone."""
    if zone:
        env.setenv("CODETEAM_ZONE", zone)
    dirs = checked_dirs(zt, env)
    for key in ("", "suite test-test-times"):
        assert zt.guard_run(tmp_path, key, "h1", False) is None
    assert dirs == [expect, expect]


def test_a_key_with_a_dir_checks_that_dir(zt, env, tmp_path):
    env.setenv("CODETEAM_ZONE", "Packages/WidgetVaultKit")
    dirs = checked_dirs(zt, env)
    zt.guard_run(tmp_path, "one Packages/WidgetVaultKit/Tests/Integration group=integration", "h1", False)
    assert dirs == ["Packages/WidgetVaultKit/Tests/Integration"]


@pytest.mark.parametrize("args, zone, expect", [([], "Packages/WidgetVaultKit", "Packages/WidgetVaultKit"),
                                                 ([""], "Packages/WidgetVaultKit", "Packages/WidgetVaultKit"),
                                                 ([], None, "."),
                                                 (["Packages/Other"], "Packages/WidgetVaultKit", "Packages/Other")])
def test_a_plain_zone_check_checks_the_lanes_zone(zt, env, tmp_path, args, zone, expect):
    """`make zone-check` with no DIR runs `zone-tool check` with no argument (or an empty one)."""
    if zone:
        env.setenv("CODETEAM_ZONE", zone)
    dirs = checked_dirs(zt, env)
    env.setattr(zt, "top", lambda: tmp_path)
    env.setattr(zt, "snapshot", lambda root: None)
    env.setattr(zt, "code_hash", lambda root, scope, snap: "h1")
    assert zt.cmd_check(args) == 0
    assert dirs == [expect]


def test_each_scope_keeps_its_clean_result_for_the_tree(zt, env, tmp_path):
    """pk/A, pk/B, then pk/A again on the same tree: pk/A is not checked twice. A new tree checks again, and the
    results for the old tree are dropped."""
    for d in ("pk/A", "pk/B"):
        (tmp_path / d).mkdir(parents=True)
    env.setenv("ZONE_CHECK_CMD", "true")
    seen = []
    env.setattr(subprocess, "run", lambda cmd, **kw: (seen.append(kw["env"]["DIR"]),
                                                      SimpleNamespace(returncode=0, stdout="", stderr=""))[1])
    g = {"checks": {}}
    for d in ("pk/A", "pk/B", "pk/A", "pk/B"):
        assert zt.run_check(tmp_path, d, "h1", g)[0] is True
    assert seen == ["pk/A", "pk/B"]
    assert zt.run_check(tmp_path, "pk/A", "h2", g)[0] is True
    assert seen == ["pk/A", "pk/B", "pk/A"]
    assert set(g["checks"]) == {"pk/A"}


def test_a_failed_check_is_not_reused(zt, env, tmp_path):
    (tmp_path / "pk" / "A").mkdir(parents=True)
    env.setenv("ZONE_CHECK_CMD", "true")
    seen = []
    env.setattr(subprocess, "run", lambda cmd, **kw: (seen.append(1),
                                                      SimpleNamespace(returncode=1, stdout="", stderr="E"))[1])
    g = {"checks": {}}
    assert zt.run_check(tmp_path, "pk/A", "h1", g)[0] is False
    assert zt.run_check(tmp_path, "pk/A", "h1", g)[0] is False
    assert seen == [1, 1]
