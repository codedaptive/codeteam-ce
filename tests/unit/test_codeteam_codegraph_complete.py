import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_codegraph_complete import CODEGRAPH_LIMIT, codegraph_complete


def answer(key="callers"):
    return {key: ["one"], "total": 1, "truncated": False,
            "definitions": [{key: ["one"], "total": 1, "truncated": False}]}


@pytest.mark.parametrize("key", ["callers", "callees"])
def test_complete_for_each_key(key):
    assert codegraph_complete(answer(key), key) is True


def test_other_key_is_incomplete():
    assert codegraph_complete(answer("callers"), "callees") is False


def test_empty_definitions_are_complete():
    assert codegraph_complete({"callers": [], "total": 0, "truncated": False, "definitions": []}, "callers") is True


@pytest.mark.parametrize("node", ["top", "definition"])
def test_truncated_is_incomplete(node):
    data = answer()
    (data if node == "top" else data["definitions"][0])["truncated"] = True
    assert codegraph_complete(data, "callers") is False


@pytest.mark.parametrize("node", ["top", "definition"])
@pytest.mark.parametrize("value", [None, "false", 0])
def test_truncated_must_be_exactly_false(node, value):
    data = answer()
    (data if node == "top" else data["definitions"][0])["truncated"] = value
    assert codegraph_complete(data, "callers") is False


@pytest.mark.parametrize("node", ["top", "definition"])
def test_short_list_is_incomplete(node):
    data = answer()
    (data if node == "top" else data["definitions"][0])["total"] = 2
    assert codegraph_complete(data, "callers") is False


@pytest.mark.parametrize("node", ["top", "definition"])
def test_missing_total_is_incomplete(node):
    data = answer()
    del (data if node == "top" else data["definitions"][0])["total"]
    assert codegraph_complete(data, "callers") is False


@pytest.mark.parametrize("node", ["top", "definition"])
@pytest.mark.parametrize("total", ["1", 1.0, True])
def test_total_must_be_an_int_not_bool(node, total):
    data = answer()
    (data if node == "top" else data["definitions"][0])["total"] = total
    assert codegraph_complete(data, "callers") is False


@pytest.mark.parametrize("value", [None, [], "text"])
def test_non_dict_answer_is_incomplete(value):
    assert codegraph_complete(value, "callers") is False


def test_non_dict_definition_is_incomplete():
    data = answer()
    data["definitions"] = [None]
    assert codegraph_complete(data, "callers") is False


def test_missing_definitions_is_incomplete():
    data = answer()
    del data["definitions"]
    assert codegraph_complete(data, "callers") is False


def test_definitions_must_be_a_list():
    data = answer()
    data["definitions"] = {}
    assert codegraph_complete(data, "callers") is False


@pytest.mark.parametrize("node", ["top", "definition"])
def test_key_value_must_be_a_list(node):
    data = answer()
    (data if node == "top" else data["definitions"][0])["callers"] = "one"
    assert codegraph_complete(data, "callers") is False


def test_codegraph_limit():
    assert CODEGRAPH_LIMIT == 10000
