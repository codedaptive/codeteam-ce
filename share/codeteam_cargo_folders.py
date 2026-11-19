"""Where each Cargo package of a workspace lives.

Reach (bin/codeteam-land) turns a Cargo.lock change into the crates it changes; the lock names packages, and this
map gives each name its folder. Build output (target), node_modules and dot folders hold no workspace packages and
are not walked.
"""
import os
import tomllib
from pathlib import Path

_SKIPPED = {"target", "node_modules"}


def cargo_package_folders(workspace: Path) -> dict[str, str | None] | None:
    """{package name: folder relative to `workspace` as posix, "." for the root} for every Cargo.toml with a
    [package] name; a name found in two folders maps to None; an unparsable Cargo.toml is skipped. None when
    `workspace` has no Cargo.toml of its own."""
    if not (workspace / "Cargo.toml").is_file():
        return None
    folders: dict[str, str | None] = {}
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in _SKIPPED and not d.startswith(".")]
        if "Cargo.toml" not in files:
            continue
        try:
            name = tomllib.loads((Path(root) / "Cargo.toml").read_text()).get("package", {}).get("name")
        except tomllib.TOMLDecodeError:
            continue
        if name is not None:
            folders[name] = None if name in folders else Path(root).relative_to(workspace).as_posix()
    return folders
