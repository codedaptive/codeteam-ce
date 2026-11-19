"""D562: unnamed changed test files do not force the whole integration folder."""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_reaching_tests import reaching_tests


@pytest.fixture
def repo(tmp_path):
    files = {
        "tests/integration/named.py": "open('lib/target.py')\n",
        "tests/integration/unnamed.py": "print('independent')\n",
        "tests/integration/conftest.py": "# configuration\n",
        "tests/integration/helpers/helper.py": "# helper\n",
        "tests/runtime/test_x.py": "pass\n",
        "lib/foo_test.py": "pass\n",
        "lib/target.py": "pass\n",
        "data/unreferenced.bin": "data\n",
        "pkg/Tests/check.swift": "// check\n",
        "pkg/__tests__/check.js": "// check\n",
        "pkg/test/check.js": "// check\n",
        "pkg/foo_tests.js": "// check\n",
        "pkg/FooTests.swift": "// check\n",
        "pkg/test_standalone.py": "pass\n",
    }
    for path, text in files.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    return tmp_path


def test_unnamed_test_in_tests_folder_runs_only_always_run_scripts(repo):
    assert reaching_tests(repo, "tests/integration", ["tests/runtime/test_x.py"], (".md",)) == [
        "tests/integration/unnamed.py"
    ]


def test_unnamed_test_suffix_outside_test_folder_runs_only_always_run_scripts(repo):
    assert reaching_tests(repo, "tests/integration", ["lib/foo_test.py"], (".md",)) == [
        "tests/integration/unnamed.py"
    ]


@pytest.mark.parametrize("path", [
    "pkg/Tests/check.swift",
    "pkg/__tests__/check.js",
    "pkg/test/check.js",
    "pkg/foo_tests.js",
    "pkg/FooTests.swift",
    "pkg/test_standalone.py",
])
def test_other_default_test_patterns_run_only_always_run_scripts(repo, path):
    assert reaching_tests(repo, "tests/integration", [path], (".md",)) == [
        "tests/integration/unnamed.py"
    ]


def test_unnamed_non_test_still_runs_whole_folder(repo):
    assert reaching_tests(repo, "tests/integration", ["data/unreferenced.bin"], (".md",)) is None


def test_unnamed_test_and_named_library_select_reaching_and_always_run_scripts(repo):
    assert reaching_tests(repo, "tests/integration", ["tests/runtime/test_x.py", "lib/target.py"], (".md",)) == [
        "tests/integration/named.py",
        "tests/integration/unnamed.py",
    ]


def test_unnamed_test_and_unnamed_non_test_still_run_whole_folder(repo):
    assert reaching_tests(repo, "tests/integration", ["tests/runtime/test_x.py", "data/unreferenced.bin"],
                          (".md",)) is None


@pytest.mark.parametrize("path", ["tests/integration/conftest.py", "tests/integration/helpers/helper.py"])
def test_non_script_inside_integration_folder_still_runs_whole_folder(repo, path):
    assert reaching_tests(repo, "tests/integration", [path], (".md",)) is None
