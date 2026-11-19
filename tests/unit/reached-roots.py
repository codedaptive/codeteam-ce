#!/usr/bin/env -S python3 -u
"""Narrow roots by their dependency scopes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_reached_roots import doc_entries, reached_roots


def test_order_and_dependencies():
    scopes = {"b": ["b", "a"], "a": ["a"], "c": ["c"]}
    assert reached_roots(["b", "c", "a"], ["a/src/lib.rs"], scopes.get) == ["b", "a"]


def test_none_dot_and_empty_are_whole_tree():
    scopes = {"none": None, "dot": ["."], "empty": [""], "other": ["other"]}
    assert reached_roots(["none", "dot", "empty", "other"], ["some/file"], scopes.get) == ["none", "dot", "empty"]


def test_exclusions():
    scope = lambda root: ["kit!rust!generated"]
    assert reached_roots(["kit"], ["kit/src/a.swift"], scope) == ["kit"]
    for path in ("kit/rust", "kit/rust/src/lib.rs", "kit/generated/a", "kitten/a"):
        assert reached_roots(["kit"], [path], scope) == [], path


def test_globs():
    assert reached_roots(["x", "y"], ["spec/a.rb"], lambda r: {"x": ["spec/**"], "y": ["tests/**"]}[r]) == ["x"]


def test_no_files():
    assert reached_roots(["all"], [], lambda r: None) == []


PACKAGES = {"app", "kit", "kit/rust"}   # folders holding a Package.swift or Cargo.toml


def test_doc_entries_keep_the_root_and_non_packages():
    entries = ["app!rust", "app/Sources/App", "docs/engineering", "kit", "scripts"]
    assert doc_entries("app", entries, PACKAGES.__contains__) == [
        "app!rust", "app/Sources/App", "docs/engineering", "scripts"]


def test_a_dependency_document_reaches_no_dependent():
    scope = {"app": ["app!rust", "kit", "scripts"], "kit": ["kit!rust", "scripts"]}
    doc_scope = lambda root: doc_entries(root, scope[root], PACKAGES.__contains__)
    assert reached_roots(["app", "kit"], ["kit/AGENTS.md"], doc_scope) == ["kit"]


def test_a_document_in_a_folder_read_by_path_still_reaches():
    scope = lambda root: doc_entries(root, ["app", "docs/engineering"], PACKAGES.__contains__)
    assert reached_roots(["app"], ["docs/engineering/COOKBOOK.md"], scope) == ["app"]


def test_doc_entries_whole_tree_stays_whole():
    assert doc_entries("tools", None, PACKAGES.__contains__) is None


failed = 0
for name, test in list(globals().items()):
    if name.startswith("test_") and callable(test):
        try:
            test()
            print(f"PASS {name}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
print(f"{failed} failed" if failed else "all passed")
sys.exit(bool(failed))
