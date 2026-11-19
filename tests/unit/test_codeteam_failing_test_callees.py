import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_failing_test_callees import failing_test_callees


def complete_answer(targets=None, callees=None):
    callees = callees or []
    return {"symbol": "test_one", "targets": targets or [], "definitions": [
        {"definition": {"filePath": "tests/test_a.py"}, "callees": callees,
         "total": len(callees), "limit": 10000, "truncated": False}],
        "callees": callees, "total": len(callees), "limit": 10000, "truncated": False}


def test_query_requests_the_full_limit(tmp_path):
    (tmp_path / ".codegraph").mkdir()
    run = Mock(return_value=json.dumps(complete_answer()))
    failing_test_callees(tmp_path, ["tests/test_a.py::Suite.test_one()"], run)
    run.assert_called_once_with(["codegraph", "callees", "test_one", "-p", str(tmp_path), "-j", "-l", "10000"])


def test_without_index_never_runs_codegraph(tmp_path):
    run = Mock()
    assert failing_test_callees(tmp_path, ["tests/test_a.py::test_one"], run) == ([], [])
    run.assert_not_called()


def test_targets_and_callees_are_relative_deduplicated_and_in_tree(tmp_path):
    (tmp_path / ".codegraph").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src/a.py").touch()
    (tmp_path / "src/b.py").touch()
    run = Mock(return_value=json.dumps(complete_answer(
        [{"filePath": "src/a.py"}], [{"filePath": str(tmp_path / "src/b.py")},
        {"filePath": "src/a.py"}, {"filePath": "/usr/lib/external.py"}, {"filePath": "../outside.py"}])))
    assert failing_test_callees(tmp_path, ["tests/test_a.py::Suite.test_one()"], run) == (
        [["src/a.py", None], ["src/b.py", None]], [])
    run.assert_called_once_with(["codegraph", "callees", "test_one", "-p", str(tmp_path), "-j", "-l", "10000"])


def test_none_and_bad_json_are_ignored_per_test(tmp_path):
    (tmp_path / ".codegraph").mkdir()
    (tmp_path / "ok.py").touch()
    run = Mock(side_effect=[None, "not json", json.dumps(complete_answer(callees=[{"filePath": "ok.py"}]))])
    assert failing_test_callees(tmp_path, ["a::test_a", "b::test_b", "c::test_c"], run) == (
        [["ok.py", None]], ["a::test_a", "b::test_b"])
    assert [call.args[0][2] for call in run.call_args_list] == ["test_a", "test_b", "test_c"]


def test_repo_index_is_used_when_tree_has_no_index_and_only_existing_tree_files_count(tmp_path):
    repo = tmp_path / "repo"
    tree = repo / "worktree"
    (repo / ".codegraph").mkdir(parents=True)
    (tree / "src").mkdir(parents=True)
    (tree / "src/a.py").touch()
    (repo / "repo-only.py").touch()
    run = Mock(return_value=json.dumps(complete_answer(
        [{"filePath": "worktree/src/a.py"}], [{"filePath": str(tree / "src/a.py")},
        {"filePath": "worktree/src/missing.py"}, {"filePath": "repo-only.py"}])))
    assert failing_test_callees(tree, ["tests/test_a.py::test_one"], run=run, repo=repo) == ([["src/a.py", None]], [])
    run.assert_called_once_with(["codegraph", "callees", "test_one", "-p", str(repo), "-j", "-l", "10000"])


def test_no_index_in_tree_or_repo_never_runs_codegraph(tmp_path):
    tree = tmp_path / "tree"
    repo = tmp_path / "repo"
    tree.mkdir()
    repo.mkdir()
    run = Mock()
    assert failing_test_callees(tree, ["tests/test_a.py::test_one"], run=run, repo=repo) == ([], [])
    run.assert_not_called()


def test_tree_index_takes_precedence_over_repo_index(tmp_path):
    tree = tmp_path / "tree"
    repo = tmp_path / "repo"
    (tree / ".codegraph").mkdir(parents=True)
    (repo / ".codegraph").mkdir(parents=True)
    (tree / "a.py").touch()
    run = Mock(return_value=json.dumps(complete_answer([{"filePath": "a.py"}])))
    assert failing_test_callees(tree, ["test_one"], run=run, repo=repo) == ([["a.py", None]], [])
    run.assert_called_once_with(["codegraph", "callees", "test_one", "-p", str(tree), "-j", "-l", "10000"])


def test_repo_relative_path_is_kept_when_tree_has_it_and_dropped_when_not(tmp_path):
    tree = tmp_path / "tree"
    repo = tmp_path / "repo"
    (tree / "src").mkdir(parents=True)
    (repo / ".codegraph").mkdir(parents=True)
    (repo / "src").mkdir()
    (tree / "src/a.py").touch()
    (repo / "src/a.py").touch()
    (repo / "src/gone.py").touch()
    run = Mock(return_value=json.dumps(complete_answer(
        [{"filePath": "src/a.py"}], [{"filePath": str(repo / "src/gone.py")}])) )
    assert failing_test_callees(tree, ["test_one"], run=run, repo=repo) == ([["src/a.py", None]], [])
    run.assert_called_once_with(["codegraph", "callees", "test_one", "-p", str(repo), "-j", "-l", "10000"])


def test_missing_indexed_path_inside_tree_is_dropped(tmp_path):
    (tmp_path / ".codegraph").mkdir()
    run = Mock(return_value=json.dumps(complete_answer([{"filePath": "missing.py"}])))
    assert failing_test_callees(tmp_path, ["test_one"], run=run) == ([], [])


def test_complete_answer_without_targets_and_with_extra_callees(tmp_path):
    (tmp_path / ".codegraph").mkdir()
    (tmp_path / "ok.py").touch()
    answer = complete_answer(callees=[{"filePath": "ok.py"}])
    del answer["targets"]
    answer["total"] = 0
    answer["definitions"][0]["total"] = 0
    run = Mock(return_value=json.dumps(answer))
    assert failing_test_callees(tmp_path, ["test_one"], run) == ([["ok.py", None]], [])


@pytest.mark.parametrize("case", [
    "top_truncated", "definition_truncated", "top_short", "definition_short",
    "top_missing_truncated", "top_missing_total", "top_missing_callees", "missing_definitions",
    "definition_missing_truncated", "definition_missing_total", "definition_missing_callees",
    "definition_not_object", "definitions_not_list", "top_callees_not_list", "definition_callees_not_list",
    "top_bool_total", "definition_bool_total", "none", "bad_json", "not_found", "array", "null",
])
def test_incomplete_answer_discards_all_its_paths_but_keeps_complete_answers(tmp_path, case):
    (tmp_path / ".codegraph").mkdir()
    (tmp_path / "partial.py").touch()
    (tmp_path / "ok.py").touch()
    answer = complete_answer([{"filePath": "partial.py"}], [{"filePath": "partial.py"}])
    definition = answer["definitions"][0]
    if case == "top_truncated":
        answer["truncated"] = True
    elif case == "definition_truncated":
        definition["truncated"] = True
    elif case == "top_short":
        answer["total"] = 2
    elif case == "definition_short":
        definition["total"] = 2
    elif case.startswith("top_missing_"):
        del answer[case.removeprefix("top_missing_")]
    elif case == "missing_definitions":
        del answer["definitions"]
    elif case.startswith("definition_missing_"):
        del definition[case.removeprefix("definition_missing_")]
    elif case == "definition_not_object":
        answer["definitions"] = [None]
    elif case == "definitions_not_list":
        answer["definitions"] = None
    elif case == "top_callees_not_list":
        answer["callees"] = None
    elif case == "definition_callees_not_list":
        definition["callees"] = None
    elif case == "top_bool_total":
        answer["total"] = True
    elif case == "definition_bool_total":
        definition["total"] = True
    outputs = {"none": None, "bad_json": "not json", "not_found": 'ℹ Symbol "x" not found\n',
               "array": "[]", "null": "null"}
    bad = outputs[case] if case in outputs else json.dumps(answer)
    good = json.dumps(complete_answer(callees=[{"filePath": "ok.py"}]))
    run = Mock(side_effect=[bad, good, bad])
    assert failing_test_callees(tmp_path, ["a::test_bad", "b::test_good", "a::test_bad"], run) == (
        [["ok.py", None]], ["a::test_bad"])


def test_identifiers_only_skip_vitest_and_spaced_names(tmp_path):
    (tmp_path / ".codegraph").mkdir()
    (tmp_path / "callee.py").touch()
    answer = json.dumps(complete_answer(callees=[{"filePath": "callee.py"}]))
    run = Mock(side_effect=lambda cmd: answer if cmd[2] == "test_y" else None)

    assert failing_test_callees(tmp_path, [
        "__tests__/a.test.ts > d > t", "a name with spaces", "tests/x.py::test_y",
    ], run) == ([["callee.py", None]], [])
    run.assert_called_once_with(["codegraph", "callees", "test_y", "-p", str(tmp_path), "-j", "-l", "10000"])


def test_identifiers_only_keep_missing_identifier_incomplete(tmp_path):
    (tmp_path / ".codegraph").mkdir()
    run = Mock(return_value='ℹ Symbol "test_gone" not found\n')

    assert failing_test_callees(tmp_path, [
        "src/b.test.ts > suite > works", "tests/x.py::test_gone",
    ], run) == ([], ["tests/x.py::test_gone"])
    run.assert_called_once_with(["codegraph", "callees", "test_gone", "-p", str(tmp_path), "-j", "-l", "10000"])


@pytest.mark.parametrize("name", [
    "tests/x.py::test_y[case]",
    "tests/x.py::C::test_y[1.5]",
    "tests/x.py::test_y[a/b]",
])
def test_paramnames_case_id_is_removed_before_symbol_split(tmp_path, name):
    (tmp_path / ".codegraph").mkdir()
    (tmp_path / "callee.py").touch()
    run = Mock(return_value=json.dumps(complete_answer(callees=[{"filePath": "callee.py"}])))

    assert failing_test_callees(tmp_path, [name], run) == ([["callee.py", None]], [])
    run.assert_called_once_with(["codegraph", "callees", "test_y", "-p", str(tmp_path), "-j", "-l", "10000"])


@pytest.mark.parametrize("name", [
    "tests/x[1].py::test_y[case]",
    "tests/x.py::test_y[a::b]",
    "tests/x.py::test_y[a[1]]",
])
def test_paramnames_cut_starts_at_the_bracket_opening_the_trailing_case_id(tmp_path, name):
    (tmp_path / ".codegraph").mkdir()
    (tmp_path / "callee.py").touch()
    run = Mock(return_value=json.dumps(complete_answer(callees=[{"filePath": "callee.py"}])))

    assert failing_test_callees(tmp_path, [name], run) == ([["callee.py", None]], [])
    run.assert_called_once_with(["codegraph", "callees", "test_y", "-p", str(tmp_path), "-j", "-l", "10000"])


def test_paramnames_cases_share_query_and_return_callee_once(tmp_path):
    (tmp_path / ".codegraph").mkdir()
    (tmp_path / "callee.py").touch()
    run = Mock(return_value=json.dumps(complete_answer(callees=[{"filePath": "callee.py"}])))

    assert failing_test_callees(tmp_path, [
        "tests/x.py::test_y[first]", "tests/x.py::test_y[second]",
    ], run) == ([["callee.py", None]], [])
    run.assert_called_once_with(["codegraph", "callees", "test_y", "-p", str(tmp_path), "-j", "-l", "10000"])


@pytest.mark.parametrize("answer", [
    'ℹ Symbol "test_y" not found\n',
    json.dumps({"truncated": True}),
])
def test_paramnames_incomplete_query_names_each_case_once_in_order(tmp_path, answer):
    (tmp_path / ".codegraph").mkdir()
    run = Mock(return_value=answer)

    assert failing_test_callees(tmp_path, [
        "tests/x.py::test_y[first]", "tests/x.py::test_y[second]", "tests/x.py::test_y[first]",
    ], run) == ([], ["tests/x.py::test_y[first]", "tests/x.py::test_y[second]"])
    run.assert_called_once_with(["codegraph", "callees", "test_y", "-p", str(tmp_path), "-j", "-l", "10000"])


def test_paramnames_skip_vitest_and_spaced_names_alongside_case(tmp_path):
    (tmp_path / ".codegraph").mkdir()
    (tmp_path / "callee.py").touch()
    answer = json.dumps(complete_answer(callees=[{"filePath": "callee.py"}]))
    run = Mock(side_effect=lambda cmd: answer if cmd[2] == "test_y" else None)

    assert failing_test_callees(tmp_path, [
        "__tests__/a.test.ts > d > t", "a name with spaces", "tests/x.py::test_y[case]",
    ], run) == ([["callee.py", None]], [])
    run.assert_called_once_with(["codegraph", "callees", "test_y", "-p", str(tmp_path), "-j", "-l", "10000"])
