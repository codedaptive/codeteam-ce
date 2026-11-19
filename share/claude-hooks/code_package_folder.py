"""The code package folder a path lies in (D587: the orchestrator holds only root files, docs,
manifests and scripts, so its guard asks which package an edit falls in).

A code package folder is a folder below the repository root holding one of PACKAGE_MARKERS.
The repository root is never one, even with a marker of its own: a root Cargo.toml is a
workspace manifest, which the orchestrator keeps. Pure stdlib; reads only the folders it walks.
"""
import os
from pathlib import Path

PACKAGE_MARKERS = ("Cargo.toml", "Package.swift", "pyproject.toml")


def code_package_folder(path: str | Path, repo_root: str | Path) -> Path | None:
    """The nearest folder at or above path, strictly below repo_root, holding a marker on disk;
    path itself counts when it is such a folder. A path named for a marker makes its parent the
    package even before the file exists (a new package being made), unless the parent is the
    root. path need not exist. Both are compared as real paths, so a symlink counts where it
    points. None outside repo_root or when no folder qualifies."""
    real = Path(os.path.realpath(path))
    root = Path(os.path.realpath(repo_root))
    if real == root or root not in real.parents:
        return None
    if real.name in PACKAGE_MARKERS and real.parent != root:
        return real.parent
    for folder in [real, *real.parents]:
        if folder == root:
            return None
        if any((folder / m).is_file() for m in PACKAGE_MARKERS):
            return folder
    return None
