"""zone-tool test-one runs the scripts in tests/unit and tests/integration as Stage 2 does,
and those in tests/validation as Stage 6's validate-suite does.

codeteam-land's Stage 2 (repo_test_steps) runs every .py and .sh directly in tests/unit (its unit step) and
tests/integration (its integration step), a .py that is not a pytest file by name as `python3 <file>`. test-one ran an
owned file only if it was a test by name, and pytest over those folders collects test_*.py only, so a lane owning
tests/unit/land-*.py got none of them run and a PASS record. The plan is checked on a small folder tree; nothing runs.
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
        loader = importlib.machinery.SourceFileLoader("zone_tool_repo_scripts", str(ROOT / "bin" / "zone-tool"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = dont_write_bytecode


@pytest.fixture
def repo(tmp_path):
    for rel in ("tests/unit/land-a.py", "tests/unit/test_b.py", "tests/unit/conftest.py", "tests/unit/__init__.py",
                "tests/unit/c.sh", "tests/unit/notes.txt", "tests/integration/land-flow.py",
                "tests/integration/test_e2e.py", "tests/validation/land-docs.py", "tests/validation/test_rate.py",
                "tests/name_of.py", "tests/zone-guard.sh", "tests/run.sh"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("")
    return tmp_path


def plan(zt, repo, rel, owned, group="unit"):
    return zt._test_one_plan(repo / rel, rel, owned, group)


def test_an_owned_unit_script_runs_as_a_script_in_the_unit_group(zt, repo):
    assert plan(zt, repo, "tests/unit/land-a.py", True) == ([("script", "tests/unit/land-a.py")], [])


def test_an_owned_integration_script_is_skipped_in_the_unit_group_and_runs_in_its_own(zt, repo):
    rel = "tests/integration/land-flow.py"
    assert plan(zt, repo, rel, True) == ([], [(rel, "integration")])
    assert plan(zt, repo, rel, True, "integration") == ([("script", rel)], [])


def test_a_script_given_as_dir_runs_whatever_the_group(zt, repo):
    rel = "tests/integration/land-flow.py"
    assert plan(zt, repo, rel, False) == ([("script", rel)], [])


def test_an_owned_helper_outside_the_repo_test_folders_still_does_not_run(zt, repo):
    assert plan(zt, repo, "tests/name_of.py", True) == ([], [])


def test_owned_pytest_files_and_conftest_keep_their_rules(zt, repo):
    assert plan(zt, repo, "tests/unit/test_b.py", True) == ([("py", "tests/unit/test_b.py")], [])
    assert plan(zt, repo, "tests/unit/conftest.py", True) == ([], [])


def test_the_unit_folder_runs_pytest_then_each_script_of_its_group(zt, repo):
    runs, skipped = plan(zt, repo, "tests/unit", False)
    assert runs == [("py", "tests/unit"), ("script", "tests/unit/land-a.py"), ("sh", "tests/unit/c.sh")]
    assert skipped == []


def test_the_unit_folder_in_the_integration_group_runs_pytest_only(zt, repo):
    runs, skipped = plan(zt, repo, "tests/unit", False, "integration")
    assert runs == [("py", "tests/unit")]
    assert sorted(skipped) == [("tests/unit/c.sh", "unit"), ("tests/unit/land-a.py", "unit")]


def test_a_folder_holding_the_repo_test_folders_reaches_their_scripts_and_keeps_tests_sh(zt, repo):
    runs, skipped = plan(zt, repo, "tests", True)
    assert runs == [("py", "tests"), ("script", "tests/unit/land-a.py"), ("sh", "tests/zone-guard.sh"),
                    ("sh", "tests/unit/c.sh")]
    assert ("tests/run.sh", "run.sh") in skipped
    assert ("tests/integration/land-flow.py", "integration") in skipped


def test_a_dot_slash_spelling_is_the_same_folder(zt, repo):
    assert plan(zt, repo, "./tests/unit/land-a.py", True) == ([("script", "./tests/unit/land-a.py")], [])


def test_a_validation_script_given_as_dir_runs_as_a_script_not_under_pytest(zt, repo):
    # land-docs.py printed all PASS and ended sys.exit(0); under pytest that is INTERNALERROR and a FAIL record.
    rel = "tests/validation/land-docs.py"
    assert plan(zt, repo, rel, False, "validation") == ([("script", rel)], [])


def test_an_owned_validation_script_runs_only_in_the_validation_group(zt, repo):
    rel = "tests/validation/land-docs.py"
    assert plan(zt, repo, rel, True) == ([], [(rel, "validation")])
    assert plan(zt, repo, rel, True, "integration") == ([], [(rel, "validation")])
    assert plan(zt, repo, rel, True, "validation") == ([("script", rel)], [])


def test_the_validation_folder_runs_pytest_then_its_scripts_in_the_validation_group(zt, repo):
    runs, skipped = plan(zt, repo, "tests/validation", False, "validation")
    assert runs == [("py", "tests/validation"), ("script", "tests/validation/land-docs.py")]
    assert skipped == []
