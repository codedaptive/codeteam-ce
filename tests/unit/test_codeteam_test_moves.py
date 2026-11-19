import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
import codeteam_test_moves as tm


SHA = "a" * 40
OTHER_SHA = "b" * 40


def rename(old, new, status="R100"):
    return f":100644 100644 {SHA} {OTHER_SHA} {status}\0{old}\0{new}\0"


def modified(path, old_mode="100644", new_mode="100644"):
    return f":{old_mode} {new_mode} {SHA} {OTHER_SHA} M\0{path}\0"


def lines_for(lines):
    return lines.__getitem__


def test_exact_move_into_integration_removes_both_paths_from_code():
    raw = rename("tests/unit/test_x.py", "tests/integration/test_x.py")
    code = ["tests/unit/test_x.py", "src/other.py", "tests/integration/test_x.py"]
    assert tm.test_moves(raw, lines_for({}), code) == (
        [{"path": "tests/integration/test_x.py", "from": "tests/unit/test_x.py",
          "to": "tests/integration/test_x.py", "group": "integration"}],
        ["src/other.py"],
    )


def test_exact_move_into_validation_removes_both_paths_from_code():
    raw = rename("tests/unit/test_x.py", "tests/validation/test_x.py")
    code = ["tests/unit/test_x.py", "src/other.py", "tests/validation/test_x.py"]
    assert tm.test_moves(raw, lines_for({}), code) == (
        [{"path": "tests/validation/test_x.py", "from": "tests/unit/test_x.py",
          "to": "tests/validation/test_x.py", "group": "validation"}],
        ["src/other.py"],
    )


def test_exact_move_into_unit_keeps_both_paths_in_code():
    raw = rename("tests/integration/test_x.py", "tests/unit/test_x.py")
    code = ["tests/integration/test_x.py", "src/other.py", "tests/unit/test_x.py"]
    assert tm.test_moves(raw, lines_for({}), code) == (
        [{"path": "tests/unit/test_x.py", "from": "tests/integration/test_x.py",
          "to": "tests/unit/test_x.py", "group": "unit"}],
        ["tests/integration/test_x.py", "src/other.py", "tests/unit/test_x.py"],
    )


def test_deepest_group_folder_wins():
    raw = rename("tests/unit/test_x.py", "tests/integration/validation/test_x.py")
    assert tm.test_moves(raw, lines_for({}), ["tests/unit/test_x.py", "tests/integration/validation/test_x.py"]) == (
        [{"path": "tests/integration/validation/test_x.py", "from": "tests/unit/test_x.py",
          "to": "tests/integration/validation/test_x.py", "group": "validation"}], [],
    )


def test_inexact_rename_is_not_a_move():
    raw = rename("tests/unit/test_x.py", "tests/integration/test_x.py", "R087")
    assert tm.test_moves(raw, lines_for({}), ["tests/unit/test_x.py", "tests/integration/test_x.py"]) == (
        [], ["tests/unit/test_x.py", "tests/integration/test_x.py"]
    )


@pytest.mark.parametrize("name", ["x.py", "conftest.py", "helpers.py"])
def test_folder_alone_does_not_make_a_test_file(name):
    old, new = f"tests/unit/{name}", f"tests/integration/{name}"
    assert tm.test_moves(rename(old, new), lines_for({}), [old, new]) == ([], [old, new])


def test_rename_to_path_without_group_is_not_a_move():
    raw = rename("tests/unit/test_x.py", "tests/test_x.py")
    assert tm.test_moves(raw, lines_for({}), ["tests/unit/test_x.py", "tests/test_x.py"]) == (
        [], ["tests/unit/test_x.py", "tests/test_x.py"]
    )


def test_team_glob_recognizes_both_names():
    raw = rename("tests/unit/land-a.py", "tests/integration/land-a.py")
    assert tm.test_moves(raw, lines_for({}), ["tests/unit/land-a.py", "tests/integration/land-a.py"],
                         globs=["tests/*/land-*.py"]) == (
        [{"path": "tests/integration/land-a.py", "from": "tests/unit/land-a.py",
          "to": "tests/integration/land-a.py", "group": "integration"}], []
    )


def test_team_glob_name_is_not_recognized_without_glob():
    raw = rename("tests/unit/land-a.py", "tests/integration/land-a.py")
    assert tm.test_moves(raw, lines_for({}), ["tests/unit/land-a.py", "tests/integration/land-a.py"]) == (
        [], ["tests/unit/land-a.py", "tests/integration/land-a.py"]
    )


def test_marker_only_change_into_integration():
    raw = modified("tests/test_y.py")
    lines = {"tests/test_y.py": (
        ['pytestmark = gate(os.environ.get("CODETEAM_TEST_GROUP") == "integration")'],
        ['if os.environ.get("CODETEAM_TEST_GROUP"): pass'],
    )}
    assert tm.test_moves(raw, lines_for(lines), ["tests/test_y.py", "src/other.py"]) == (
        [{"path": "tests/test_y.py", "from": "tests/test_y.py", "to": "tests/test_y.py",
          "group": "integration"}], ["src/other.py"]
    )


def test_marker_group_comes_from_added_not_removed_lines():
    raw = modified("tests/test_y.py")
    lines = {"tests/test_y.py": (
        ['pytestmark = gate(os.environ.get("CODETEAM_TEST_GROUP") == "integration")'],
        ['pytestmark = gate(os.environ.get("CODETEAM_TEST_GROUP") == "unit")'],
    )}
    assert tm.test_moves(raw, lines_for(lines), ["tests/test_y.py"]) == (
        [{"path": "tests/test_y.py", "from": "tests/test_y.py", "to": "tests/test_y.py",
          "group": "integration"}], []
    )


def test_marker_with_non_gate_added_line_is_not_a_move():
    raw = modified("tests/test_y.py")
    lines = {"tests/test_y.py": (['CODETEAM_TEST_GROUP == "integration"', 'assert result == 1'], [])}
    assert tm.test_moves(raw, lines_for(lines), ["tests/test_y.py"]) == ([], ["tests/test_y.py"])


def test_marker_with_non_gate_removed_line_is_not_a_move():
    raw = modified("tests/test_y.py")
    lines = {"tests/test_y.py": (['CODETEAM_TEST_GROUP == "integration"'], ['assert result == 1'])}
    assert tm.test_moves(raw, lines_for(lines), ["tests/test_y.py"]) == ([], ["tests/test_y.py"])


def test_marker_naming_two_groups_in_added_lines_is_not_a_move():
    raw = modified("tests/test_y.py")
    lines = {"tests/test_y.py": (['CODETEAM_TEST_GROUP in ("integration", "validation")'], [])}
    assert tm.test_moves(raw, lines_for(lines), ["tests/test_y.py"]) == ([], ["tests/test_y.py"])


def test_marker_in_group_folder_is_not_a_move():
    raw = modified("tests/unit/test_y.py")
    lines = {"tests/unit/test_y.py": (['CODETEAM_TEST_GROUP == "integration"'], [])}
    assert tm.test_moves(raw, lines_for(lines), ["tests/unit/test_y.py"]) == ([], ["tests/unit/test_y.py"])


def test_marker_with_mode_change_is_not_a_move():
    raw = modified("tests/test_y.py", new_mode="100755")
    lines = {"tests/test_y.py": (['CODETEAM_TEST_GROUP == "integration"'], [])}
    assert tm.test_moves(raw, lines_for(lines), ["tests/test_y.py"]) == ([], ["tests/test_y.py"])


def test_marker_on_non_test_file_is_not_a_move():
    raw = modified("tests/helpers.py")
    lines = {"tests/helpers.py": (['CODETEAM_TEST_GROUP == "integration"'], [])}
    assert tm.test_moves(raw, lines_for(lines), ["tests/helpers.py"]) == ([], ["tests/helpers.py"])


def test_changed_lines_only_called_for_marker_candidates():
    calls = []
    rows = (rename("tests/unit/test_x.py", "tests/integration/test_x.py")
            + modified("tests/unit/test_y.py")
            + modified("tests/test_mode.py", new_mode="100755")
            + modified("tests/helpers.py")
            + modified("tests/test_candidate.py"))

    def changed_lines(path):
        calls.append(path)
        return {"tests/test_candidate.py": (['CODETEAM_TEST_GROUP == "integration"'], [])}[path]

    moves, code_left = tm.test_moves(rows, changed_lines, ["tests/test_candidate.py"])
    assert calls == ["tests/test_candidate.py"]
    assert moves == [
        {"path": "tests/integration/test_x.py", "from": "tests/unit/test_x.py",
         "to": "tests/integration/test_x.py", "group": "integration"},
        {"path": "tests/test_candidate.py", "from": "tests/test_candidate.py",
         "to": "tests/test_candidate.py", "group": "integration"},
    ]
    assert code_left == []


def test_copy_is_not_a_move():
    raw = rename("tests/unit/test_x.py", "tests/integration/test_x.py", "C100")
    assert tm.test_moves(raw, lines_for({}), ["tests/integration/test_x.py"]) == (
        [], ["tests/integration/test_x.py"]
    )


@pytest.mark.parametrize("old,new", [
    ("tests/unit/helpers.py", "tests/integration/test_x.py"),
    ("tests/unit/test_x.py", "tests/integration/helpers.py"),
])
def test_both_rename_names_must_be_tests(old, new):
    assert tm.test_moves(rename(old, new), lines_for({}), [old, new]) == ([], [old, new])


def test_marker_with_no_changed_lines_is_not_a_move():
    assert tm.test_moves(modified("tests/test_y.py"), lines_for({"tests/test_y.py": ([], [])}),
                         ["tests/test_y.py"]) == ([], ["tests/test_y.py"])


def test_marker_group_is_a_whole_word():
    lines = {"tests/test_y.py": (['CODETEAM_TEST_GROUP == "integration_extra"'], [])}
    assert tm.test_moves(modified("tests/test_y.py"), lines_for(lines), ["tests/test_y.py"]) == (
        [], ["tests/test_y.py"]
    )
