"""D587: identify code package folders below a repository root."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share" / "claude-hooks"))
from code_package_folder import PACKAGE_MARKERS, code_package_folder


def test_package_markers():
    assert PACKAGE_MARKERS == ("Cargo.toml", "Package.swift", "pyproject.toml")


def test_file_inside_cargo_package(tmp_path):
    pkg = tmp_path / "crates/cli"
    (pkg / "src").mkdir(parents=True)
    (pkg / "Cargo.toml").touch()
    assert code_package_folder(pkg / "src/main.rs", tmp_path) == pkg.resolve()


def test_nearest_nested_package(tmp_path):
    pkg = tmp_path / "crates/cli"
    nested = pkg / "fuzz"
    (nested / "src").mkdir(parents=True)
    (pkg / "Cargo.toml").touch()
    (nested / "Cargo.toml").touch()
    assert code_package_folder(nested / "src/main.rs", tmp_path) == nested.resolve()


@pytest.mark.parametrize("marker", ["Package.swift", "pyproject.toml"])
def test_other_package_markers(tmp_path, marker):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / marker).touch()
    assert code_package_folder(str(pkg / "new.file"), str(tmp_path)) == pkg.resolve()


def test_root_marker_does_not_make_root_a_package(tmp_path):
    (tmp_path / "Cargo.toml").touch()
    assert code_package_folder(tmp_path / "src/x.rs", tmp_path) is None


def test_root_marker_path_is_not_a_package(tmp_path):
    (tmp_path / "Cargo.toml").touch()
    assert code_package_folder(tmp_path / "Cargo.toml", tmp_path) is None


def test_new_marker_names_its_parent(tmp_path):
    assert code_package_folder(tmp_path / "crates/new/Cargo.toml", tmp_path) == (tmp_path / "crates/new").resolve()


def test_package_directory_itself(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "Cargo.toml").touch()
    assert code_package_folder(pkg, tmp_path) == pkg.resolve()


def test_nonexistent_file_inside_existing_package(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "Cargo.toml").touch()
    assert code_package_folder(pkg / "new/deep/file.rs", tmp_path) == pkg.resolve()


def test_outside_repository(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "Cargo.toml").touch()
    assert code_package_folder(outside / "x.rs", repo) is None


@pytest.mark.parametrize("marker", ["Cargo.lock", "package.json"])
def test_non_markers_do_not_create_packages(tmp_path, marker):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / marker).touch()
    assert code_package_folder(pkg / "x", tmp_path) is None


def test_resolves_symlinks_before_containment(tmp_path):
    repo = tmp_path / "repo"
    pkg = repo / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "pyproject.toml").touch()
    alias = tmp_path / "alias"
    alias.symlink_to(pkg, target_is_directory=True)
    assert code_package_folder(alias / "new.py", repo) == pkg.resolve()
