"""ZUT for share/codeteam_loose_owned_tests.py (D507): the owned test files that lie in none of a lane's test roots.
A real temp folder stands in for the tree; which file is a test is the plan's answer, faked here."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "share"))

from codeteam_loose_owned_tests import loose_owned_tests  # noqa: E402


def tree_with(tmp_path, *files):
    for name in files:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("")
    return tmp_path


def plan_by_name(path, rel):
    """The fake plan: a file runs when its name starts with land- or test_."""
    return [("script", rel)] if Path(rel).name.startswith(("land-", "test_")) else []


def test_a_glob_owned_test_outside_every_root_is_loose(tmp_path):
    tree = tree_with(tmp_path, "tests/unit/land-a.py", "tests/unit/land-b.py", "tests/unit/own.py",
                     "zone/tests/test_z.py")
    owns = ["zone", "tests/unit/land-*.py", "docs"]
    assert loose_owned_tests(tree, owns, ["zone"], plan_by_name) == ["tests/unit/land-a.py", "tests/unit/land-b.py"]


def test_an_owned_file_inside_a_root_is_not_loose(tmp_path):
    tree = tree_with(tmp_path, "zone/tests/test_z.py")
    assert loose_owned_tests(tree, ["zone", "zone/tests/test_*.py"], ["zone"], plan_by_name) == []


def test_an_owned_file_that_is_no_test_is_not_loose(tmp_path):
    tree = tree_with(tmp_path, "bin/codeteam-land", "tests/unit/helper.py")
    assert loose_owned_tests(tree, ["bin/codeteam-land", "tests/unit/helper.py"], [], plan_by_name) == []


def test_owned_folders_and_unmatched_globs_add_nothing(tmp_path):
    tree = tree_with(tmp_path, "bin/land_v55/x/test_inner.py")
    assert loose_owned_tests(tree, ["bin/land_v55/[!s]*", "tests/unit/watchdog-*.py"], [], plan_by_name) == []


def test_a_root_is_matched_by_whole_folder_not_by_prefix(tmp_path):
    tree = tree_with(tmp_path, "zone-extra/test_e.py")
    assert loose_owned_tests(tree, ["zone-extra/test_e.py"], ["zone"], plan_by_name) == ["zone-extra/test_e.py"]


def test_a_file_named_twice_is_listed_once(tmp_path):
    tree = tree_with(tmp_path, "tests/unit/land-a.py")
    assert loose_owned_tests(tree, ["tests/unit/land-*.py", "tests/unit/land-a.py"], [], plan_by_name) == \
        ["tests/unit/land-a.py"]


def test_the_plan_gets_the_absolute_path_and_the_relative_name(tmp_path):
    tree = tree_with(tmp_path, "tests/unit/land-a.py")
    seen = []
    loose_owned_tests(tree, ["tests/unit/land-a.py"], [], lambda path, rel: seen.append((path, rel)) or [])
    assert seen == [(tmp_path / "tests/unit/land-a.py", "tests/unit/land-a.py")]
