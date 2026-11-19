import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]

# Zone integration (rule 11): every case runs real pytest processes over a temp repo.
pytestmark = pytest.mark.skipif(
    os.environ.get("CODETEAM_TEST_GROUP", "unit") != "integration",
    reason="integration group only; run with CODETEAM_TEST_GROUP=integration",
)


@pytest.fixture
def test_repo(tmp_path):
    tests = tmp_path / "pkg" / "tests"
    (tests / "integration").mkdir(parents=True)
    (tests / "validation").mkdir()
    (tests / "test_plain.py").write_text("def test_plain(): pass\n")
    (tests / "test_mixed.py").write_text('''\
import os
import unittest
INTEGRATION = os.environ.get("CODETEAM_TEST_GROUP", "unit") == "integration"
integration_only = unittest.skipUnless(INTEGRATION, "integration group only")
class TestMixed(unittest.TestCase):
    def test_unit_case(self): pass
    @integration_only
    def test_integration_case(self): pass
''')
    (tests / "test_module_gate.py").write_text('''\
import os
import pytest
pytestmark = pytest.mark.skipif(os.environ.get("CODETEAM_TEST_GROUP", "unit") != "integration", reason="integration group only")
def test_module_integration(): pass
''')
    (tests / "test_validation_gate.py").write_text('''\
import os
import pytest
pytestmark = pytest.mark.skipif(os.environ.get("CODETEAM_TEST_GROUP", "unit") != "validation", reason="validation group only")
def test_module_validation(): pass
''')
    (tests / "integration" / "test_in_folder.py").write_text("def test_folder_integration(): pass\n")
    (tests / "validation" / "test_in_vfolder.py").write_text("def test_folder_validation(): pass\n")
    return tmp_path


def run_pytest(repo, group, folder="pkg/tests", kind=True):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "share")
    env["CODETEAM_TEST_GROUP"] = group
    env.pop("GROUP", None)
    env.pop("PYTEST_ADDOPTS", None)
    args = [sys.executable, "-m", "pytest", "-v", "-p", "no:cacheprovider", "-p", "codeteam_kinds_pytest"]
    if kind:
        args.append(f"--codeteam-kind={group}")
    args.append(folder)
    return subprocess.run(args, cwd=repo, env=env, capture_output=True, text=True, timeout=120)


def passed_names(result):
    return {
        parts[0].split("::")[-1]
        for line in result.stdout.splitlines()
        if len(parts := line.split()) >= 2 and parts[1] == "PASSED"
    }


@pytest.mark.parametrize("group, expected", [
    ("unit", {"test_plain", "test_unit_case"}),
    ("integration", {"test_integration_case", "test_module_integration", "test_folder_integration"}),
    ("validation", {"test_module_validation", "test_folder_validation"}),
])
def test_selected_kind_runs_only_its_tests(test_repo, group, expected):
    result = run_pytest(test_repo, group)
    assert result.returncode == 0, result.stdout + result.stderr
    assert passed_names(result) == expected, result.stdout
    assert "deselected" in result.stdout


def test_without_option_plugin_leaves_selection_unchanged(test_repo):
    result = run_pytest(test_repo, "integration", kind=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert passed_names(result) == {
        "test_plain", "test_unit_case", "test_integration_case", "test_module_integration",
        "test_folder_integration", "test_folder_validation",
    }, result.stdout
    assert "deselected" not in result.stdout


def test_integration_with_only_plain_test_selects_nothing(tmp_path):
    tests = tmp_path / "plain"
    tests.mkdir()
    (tests / "test_plain.py").write_text("def test_plain(): pass\n")
    result = run_pytest(tmp_path, "integration", folder="plain")
    assert result.returncode == 5, result.stdout + result.stderr
    assert passed_names(result) == set()
    assert "1 deselected" in result.stdout


def test_item_absent_from_unit_collection_is_selected_for_integration(tmp_path):
    tests = tmp_path / "pkg" / "tests"
    tests.mkdir(parents=True)
    (tests / "conftest.py").write_text('''\
import os
def pytest_ignore_collect(collection_path, config):
    if collection_path.name == "test_group_only.py" and os.environ.get("CODETEAM_TEST_GROUP") == "unit":
        return True
''')
    (tests / "test_plain.py").write_text("def test_plain(): pass\n")
    (tests / "test_group_only.py").write_text("def test_collected_only_in_integration(): pass\n")
    result = run_pytest(tmp_path, "integration")
    assert result.returncode == 0, result.stdout + result.stderr
    assert passed_names(result) == {"test_collected_only_in_integration"}, result.stdout
    assert "1 deselected" in result.stdout


def test_failed_unit_probe_fails_the_group_run(tmp_path):
    tests = tmp_path / "pkg" / "tests"
    tests.mkdir(parents=True)
    (tests / "conftest.py").write_text('''\
import os
def pytest_sessionstart(session):
    if os.environ.get("CODETEAM_TEST_GROUP") == "unit":
        raise RuntimeError("unit probe failed")
''')
    (tests / "test_plain.py").write_text("def test_plain(): pass\n")
    result = run_pytest(tmp_path, "integration")
    output = result.stdout + result.stderr
    assert result.returncode == 4, output
    assert "the unit probe wrote no nodeids" in output, output


@pytest.mark.parametrize("group, code, expected", [
    ("integration", 0, {"test_folder_integration"}),
    ("unit", 5, set()),
])
def test_kind_folder_given_as_the_argument_keeps_its_kind(test_repo, group, code, expected):
    # No ini file: pytest's rootdir is the folder argument itself, so the kind is read from the path relative to the
    # directory pytest was started in (zone-tool starts it at the repo root).
    result = run_pytest(test_repo, group, folder="pkg/tests/integration")
    assert result.returncode == code, result.stdout + result.stderr
    assert passed_names(result) == expected, result.stdout
