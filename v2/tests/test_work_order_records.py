"""Tests for the work-order record reader (D590). Integration (rule 11): reads real files it creates under pytest's
tmp_path, since reading land/wo files is the reader's subject."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2.work_order_records import work_order_records  # noqa: E402
from conftest import integration_module  # noqa: E402

pytestmark = integration_module


def write_record(folder, filename, value):
    (folder / filename).write_text(json.dumps(value))


def test_missing_wo_folder_gives_empty_list(tmp_path):
    assert work_order_records(tmp_path) == []


def test_wo_path_that_is_not_a_directory_gives_empty_list(tmp_path):
    (tmp_path / "wo").write_text("not a directory")
    assert work_order_records(tmp_path) == []


def test_records_are_sorted_by_filename(tmp_path):
    folder = tmp_path / "wo"
    folder.mkdir()
    write_record(folder, "z.json", {"tree": "/z", "zone": "alpha", "wo": "z"})
    write_record(folder, "a.json", {"tree": "/a", "zone": "beta", "wo": "a", "extra": 7})
    assert work_order_records(tmp_path) == [
        {"tree": "/a", "zone": "beta", "wo": "a", "extra": 7},
        {"tree": "/z", "zone": "alpha", "wo": "z"},
    ]


@pytest.mark.parametrize("filename", ["one.landed.json", "one.retired.json", "one.txt"])
def test_non_open_record_files_are_skipped(tmp_path, filename):
    folder = tmp_path / "wo"
    folder.mkdir()
    write_record(folder, filename, {"tree": "/one", "zone": "alpha", "wo": "one"})
    assert work_order_records(tmp_path) == []


def test_invalid_json_is_skipped_without_losing_valid_records(tmp_path):
    folder = tmp_path / "wo"
    folder.mkdir()
    (folder / "bad.json").write_text("{bad json")
    write_record(folder, "good.json", {"tree": "/one", "zone": "alpha", "wo": "one"})
    assert work_order_records(tmp_path) == [{"tree": "/one", "zone": "alpha", "wo": "one"}]


@pytest.mark.parametrize("value", [None, [], "string", 17])
def test_non_object_json_is_skipped(tmp_path, value):
    folder = tmp_path / "wo"
    folder.mkdir()
    write_record(folder, "one.json", value)
    assert work_order_records(tmp_path) == []


@pytest.mark.parametrize("missing", ["tree", "zone", "wo"])
def test_record_missing_required_field_is_skipped(tmp_path, missing):
    folder = tmp_path / "wo"
    folder.mkdir()
    value = {"tree": "/one", "zone": "alpha", "wo": "one"}
    del value[missing]
    write_record(folder, "one.json", value)
    assert work_order_records(tmp_path) == []


@pytest.mark.parametrize("field,value", [
    ("tree", None), ("tree", 17), ("wo", None), ("wo", 17), ("zone", None), ("zone", ["alpha"]),
])
def test_record_with_non_string_field_is_skipped_without_losing_valid_records(tmp_path, field, value):
    folder = tmp_path / "wo"
    folder.mkdir()
    write_record(folder, "bad.json", {"tree": "/bad", "zone": "alpha", "wo": "bad", field: value})
    write_record(folder, "good.json", {"tree": "/one", "zone": "alpha", "wo": "one"})
    assert work_order_records(tmp_path) == [{"tree": "/one", "zone": "alpha", "wo": "one"}]


def test_unreadable_record_is_skipped_without_losing_valid_records(tmp_path):
    folder = tmp_path / "wo"
    folder.mkdir()
    (folder / "broken.json").symlink_to(folder / "missing-target")
    write_record(folder, "good.json", {"tree": "/one", "zone": "alpha", "wo": "one"})
    assert work_order_records(tmp_path) == [{"tree": "/one", "zone": "alpha", "wo": "one"}]
