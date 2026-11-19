"""zone-tool test-one runs the scripts in a path's own tests/unit, tests/integration and tests/validation as it runs the
repo test folders' (so the landing tool's land-*.py scripts can move from
tests/integration to the zone lane's zone/tests/integration).

Before, only the repo-root folders (REPO_TEST_FOLDERS) ran plain scripts, so `make zone-test-one DIR=zone` never ran a
land-*.py in zone/tests/integration, and one given as DIR went to pytest, which these import-time scripts do not
survive. The plan is checked on a small folder tree; nothing runs.
"""

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def zt():
    dont_write_bytecode = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        loader = importlib.machinery.SourceFileLoader("zone_tool_nested_kinds", str(ROOT / "bin" / "zone-tool"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = dont_write_bytecode


@pytest.fixture
def repo(tmp_path):
    for rel in ("zone/tests/test_tool.py", "zone/tests/guard.sh", "zone/tests/integration/land-alpha.py",
                "zone/tests/integration/test_flow.py", "zone/tests/integration/conftest.py",
                "zone/tests/unit/land-unit.py", "zone/tests/validation/land-docs.py",
                "zone/integration/land-not-kind.py", "zone/sub/tests/integration/land-deep.py"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("")
    return tmp_path


def plan(zt, repo, rel, owned, group="unit"):
    return zt._test_one_plan(repo / rel, rel, owned, group)


def test_the_zone_in_its_integration_run_runs_its_own_integration_scripts_and_skips_the_other_groups(zt, repo):
    runs, skipped = plan(zt, repo, "zone", True, "integration")
    assert runs == [("py", "zone"), ("script", "zone/tests/integration/land-alpha.py"), ("sh", "zone/tests/guard.sh")]
    assert skipped == [("zone/tests/unit/land-unit.py", "unit"), ("zone/tests/validation/land-docs.py", "validation")]


def test_the_zone_in_its_unit_run_runs_its_unit_scripts_and_skips_the_integration_ones(zt, repo):
    runs, skipped = plan(zt, repo, "zone", True)
    assert ("script", "zone/tests/unit/land-unit.py") in runs
    assert ("zone/tests/integration/land-alpha.py", "integration") in skipped
    assert not any(rel == "zone/tests/integration/land-alpha.py" for _, rel in runs)


def test_the_zones_tests_folder_and_its_kind_folder_reach_the_same_scripts(zt, repo):
    for rel in ("zone/tests", "zone/tests/integration"):
        runs, _ = plan(zt, repo, rel, False, "integration")
        assert ("script", "zone/tests/integration/land-alpha.py") in runs, rel


def test_a_nested_kind_script_given_as_dir_runs_as_a_script_whatever_the_group(zt, repo):
    rel = "zone/tests/integration/land-alpha.py"
    assert plan(zt, repo, rel, False) == ([("script", rel)], [])
    assert plan(zt, repo, rel, True) == ([], [(rel, "integration")])
    assert plan(zt, repo, rel, True, "integration") == ([("script", rel)], [])


def test_a_folder_named_integration_outside_a_tests_folder_is_not_a_kind_folder(zt, repo):
    assert plan(zt, repo, "zone/integration/land-not-kind.py", False) == ([("py", "zone/integration/land-not-kind.py")], [])
    runs, skipped = plan(zt, repo, "zone", True, "integration")
    assert not any("land-not-kind" in rel for _, rel in runs + skipped)


def test_only_the_paths_own_tests_folder_counts_not_one_deeper_down(zt, repo):
    runs, skipped = plan(zt, repo, "zone", True, "integration")
    assert not any("land-deep" in rel for _, rel in runs + skipped)
    runs, _ = plan(zt, repo, "zone/sub", True, "integration")
    assert ("script", "zone/sub/tests/integration/land-deep.py") in runs
