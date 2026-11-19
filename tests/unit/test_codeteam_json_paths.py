import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_json_paths import json_paths


def test_nested_paths_in_document_order():
    obj = {"path": "a", "nested": [{"file": "b"}, {"filePath": "c", "ignored": "d"}], "file": "e"}
    assert list(json_paths(obj)) == ["a", "b", "c", "e"]


def test_non_string_path_value_is_descended_into():
    assert list(json_paths({"path": {"file": "nested"}, "filePath": [{"path": "deeper"}]})) == ["nested", "deeper"]


@pytest.mark.parametrize("value", [None, True, 5, 1.5, "path"])
def test_scalars_yield_nothing(value):
    assert list(json_paths(value)) == []
