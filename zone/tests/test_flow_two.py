"""Test build-queue port detection, including missing folders and packages created after a cache miss."""

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def bq(monkeypatch):
    loader = importlib.machinery.SourceFileLoader("bq_flow_two", str(ROOT / "bin" / "codeteam-buildq"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, loader.name, module)
    loader.exec_module(module)
    module._PORTS.clear()
    return module


@pytest.fixture
def tree(tmp_path):
    for directory, manifest in {
        "kits/K": "Package.swift",
        "kits/K/rust": "Cargo.toml",
        "crates/c": "Cargo.toml",
        "crates/c/tests/sync": None,
        "v2": None,
        "zone/tests": None,
    }.items():
        (tmp_path / directory).mkdir(parents=True, exist_ok=True)
        if manifest:
            (tmp_path / directory / manifest).write_text("")
    return tmp_path


def port(bq, tree, directory):
    return bq.job_port({"key": f"one {directory} owns=", "worktree": str(tree)})


def test_swift_package_is_swift(bq, tree):
    assert port(bq, tree, "kits/K") == "swift"


def test_nested_rust_port_is_rust(bq, tree):
    assert port(bq, tree, "kits/K/rust") == "rust"


def test_crate_is_rust(bq, tree):
    assert port(bq, tree, "crates/c") == "rust"


def test_folder_inside_crate_is_rust(bq, tree):
    assert port(bq, tree, "crates/c/tests/sync") == "rust"


def test_python_folder_has_no_port(bq, tree):
    assert port(bq, tree, "v2") is None


def test_shell_test_folder_has_no_port(bq, tree):
    assert port(bq, tree, "zone/tests") is None


def test_missing_folder_keeps_old_answer(bq, tree):
    assert port(bq, tree, "gone") == "swift"


def test_non_zone_job_has_no_port(bq, tree):
    assert bq.job_port({"key": "lane testing", "worktree": str(tree)}) is None


def test_missing_folder_then_rust_crate(bq, tmp_path):
    assert port(bq, tmp_path, "new") == "swift"
    (tmp_path / "new").mkdir()
    (tmp_path / "new" / "Cargo.toml").write_text("")
    assert port(bq, tmp_path, "new") == "rust"


def test_missing_folder_then_plain_folder(bq, tmp_path):
    assert port(bq, tmp_path, "new") == "swift"
    (tmp_path / "new").mkdir()
    assert port(bq, tmp_path, "new") is None


def test_plain_folder_then_swift_package(bq, tmp_path):
    (tmp_path / "new").mkdir()
    assert port(bq, tmp_path, "new") is None
    (tmp_path / "new" / "Package.swift").write_text("")
    assert port(bq, tmp_path, "new") == "swift"
