import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_documents_only import documents_only


def _unexpected_call(_path):
    raise AssertionError("filesystem callback must not be called")


@pytest.mark.parametrize("entry", [".", ""])
def test_root_entry_does_not_inspect_path(entry):
    assert documents_only(entry, object(), (".md",), _unexpected_call, _unexpected_call) == ["."]


@pytest.mark.parametrize("entry, expected", [
    ("docs/PLUGIN_A.md", ["docs/PLUGIN_A.md"]),
    ("docs/notes.txt", ["docs/notes.txt"]),
    ("src/main.py", ["."]),
    ("docs.md/main", ["."]),
])
def test_file_scope_uses_last_component_and_suffixes(entry, expected):
    path = object()
    assert documents_only(entry, path, (".md", ".txt"), {path: True}.__getitem__, _unexpected_call) == expected


def test_document_tree_is_its_own_scope():
    path = object()
    triples = [("docs", ["guide"], ["readme.md", "notes.txt"]),
               ("docs/guide", [], ["intro.md"])]
    assert documents_only("docs", path, (".md", ".txt"),
                          {path: False}.__getitem__, {path: triples}.__getitem__) == ["docs"]


def test_git_subdirectories_are_pruned_in_place_at_each_level():
    path = object()
    top_subdirs = [".git", "guide", "assets"]
    lower_subdirs = ["examples", ".git"]
    triples = [("docs", top_subdirs, []), ("docs/guide", lower_subdirs, ["intro.md"])]
    assert documents_only("docs", path, (".md",),
                          {path: False}.__getitem__, {path: triples}.__getitem__) == ["docs"]
    assert top_subdirs == ["guide", "assets"]
    assert lower_subdirs == ["examples"]


def test_git_name_is_ignored():
    path = object()
    triples = [("docs", [], [".git", "readme.md"])]
    assert documents_only("docs", path, (".md",),
                          {path: False}.__getitem__, {path: triples}.__getitem__) == ["docs"]


def test_non_document_at_top_makes_scope_whole_tree():
    path = object()
    triples = [("docs", [], ["readme.md", "main.py"])]
    assert documents_only("docs", path, (".md",),
                          {path: False}.__getitem__, {path: triples}.__getitem__) == ["."]


def test_hidden_non_document_in_lower_directory_makes_scope_whole_tree():
    path = object()
    triples = [("docs", ["guide"], ["readme.md"]), ("docs/guide", [], [".gitkeep"])]
    assert documents_only("docs", path, (".md",),
                          {path: False}.__getitem__, {path: triples}.__getitem__) == ["."]


def test_empty_folder_is_its_own_scope():
    path = object()
    triples = [("docs", [], [])]
    assert documents_only("docs", path, (".md",),
                          {path: False}.__getitem__, {path: triples}.__getitem__) == ["docs"]


def test_empty_walk_is_its_own_scope():
    path = object()
    assert documents_only("docs", path, (".md",),
                          {path: False}.__getitem__, {path: []}.__getitem__) == ["docs"]


def test_walk_stops_after_first_non_document_triple():
    path = object()

    def triples():
        yield ("docs", ["guide"], ["readme.md"])
        yield ("docs/guide", [], ["main.py"])
        raise AssertionError("walk consumed past the non-document")

    assert documents_only("docs", path, (".md",),
                          {path: False}.__getitem__, {path: triples()}.__getitem__) == ["."]
