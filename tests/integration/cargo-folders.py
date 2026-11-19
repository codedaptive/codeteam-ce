#!/usr/bin/env -S python3 -u
"""Discover Cargo package folders in a temporary workspace."""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "share"))
from codeteam_cargo_folders import cargo_package_folders  # noqa: E402


def manifest(workspace, folder, text):
    directory = workspace / folder
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "Cargo.toml").write_text(text)


def test_workspace_members_and_skipped_directories():
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        manifest(workspace, ".", "[workspace]\nmembers = []\n")
        manifest(workspace, "crates/a", '[package]\nname = "a"\n')
        manifest(workspace, "crates/b", '[package]\nname = "bee"\n')
        manifest(workspace, "target/debug/x", '[package]\nname = "ignored-target"\n')
        manifest(workspace, ".hidden/y", '[package]\nname = "ignored-hidden"\n')
        manifest(workspace, "node_modules/z", '[package]\nname = "ignored-node"\n')
        assert cargo_package_folders(workspace) == {"a": "crates/a", "bee": "crates/b"}


def test_duplicate_names_map_to_none():
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        manifest(workspace, ".", "[workspace]\n")
        manifest(workspace, "crates/a", '[package]\nname = "same"\n')
        manifest(workspace, "crates/b", '[package]\nname = "same"\n')
        manifest(workspace, "crates/c", '[package]\nname = "other"\n')
        assert cargo_package_folders(workspace) == {"same": None, "other": "crates/c"}


def test_root_package_maps_to_dot():
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        manifest(workspace, ".", '[package]\nname = "root"\n')
        assert cargo_package_folders(workspace) == {"root": "."}


def test_no_root_manifest_is_unknown():
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        manifest(workspace, "crates/a", '[package]\nname = "a"\n')
        assert cargo_package_folders(workspace) is None


def test_unparseable_manifest_is_skipped():
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        manifest(workspace, ".", "[workspace]\n")
        manifest(workspace, "crates/broken", '[package\nname = "broken"\n')
        manifest(workspace, "crates/good", '[package]\nname = "good"\n')
        assert cargo_package_folders(workspace) == {"good": "crates/good"}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except AssertionError:
                print(f"FAIL {name}")
                raise
            print(f"PASS {name}")
    print("all passed")
