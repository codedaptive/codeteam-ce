"""Keep rebuildable build output out of Time Machine.

Time Machine runs hourly (or from the owner's own launchd job), and its local snapshot pins every block a backed-up file held until the
backup to the external disk ends, so build output that is backed up and then deleted still fills the disk. Measured on
one team: land/itest, land/landing-tree and DerivedData in work order trees were backed up; cargo-target was not (zone-tool's
warm clone excludes it).

A sticky exclusion (CSBackupSetItemExcluded with excludeByPath false, what `tmutil addexclusion` without -p does) marks
the folder itself and goes with it when the folder is deleted. So a folder is marked once it exists. The landing tool's
own trees are marked whole when they are made (land/itest, land/validate). A work tree's build output is marked when the
tree is cut, for what its warm clone brought, and by codeteam's hourly sweep (`exclude_team`) for what its builds made
since. Nothing here pre-creates a folder: an empty build folder would make the idle sweep run zone-clean and mark the tree
cleaned before anything was built, and zone-clean deletes the folders anyway. The build queue never marks anything
(zone/docs/TESTING.md: nothing on the queue path calls tmutil), so nothing here runs on it.

Measured 2026-11-12: `tmutil addexclusion` took 11 s per folder, even for one already marked (33 s for three), so a
team's ~230 folders would take 42 min; CoreServices' CSBackupSetItemExcluded wrote the same mark
(com.apple.metadata:com_apple_backup_excludeItem, "com.apple.backupd") on two folders in 67 ms, and `tmutil isexcluded`
reports them excluded. So the API marks, and tmutil is the fallback where the API cannot be loaded.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import platform
import subprocess
from pathlib import Path
from typing import Iterable

# Build output at a tree's root: codeteam's tools build into DerivedData (swift-test-xcode, xcodebuild
# -derivedDataPath) and cargo-target (codeteam-slot's CARGO_TARGET_DIR); .codegraph is the CodeGraph index, rebuilt
# from the tree.
ROOT_DIRS = ("DerivedData", "cargo-target", "target", ".build", "node_modules", ".codegraph")
# Build output beside each tracked package manifest.
BESIDE = {"Package.swift": ".build", "Cargo.toml": "target", "package.json": "node_modules"}
# Trees the landing tool makes for itself under <root>/land: marked whole. landing-tree is v5.1's, still on disk.
LAND_TREES = ("itest", "landing-tree", "validate")
BATCH = 400          # paths per tmutil call, well inside the argument limit


def build_dirs(tree: Path) -> list[Path]:
    """The build output folders that exist in a work tree: ROOT_DIRS at its root, and .build, target and node_modules
    beside each Package.swift, Cargo.toml and package.json git tracks there."""
    tree = Path(tree)
    found = {tree / d for d in ROOT_DIRS}
    try:
        r = subprocess.run(["git", "-C", str(tree), "ls-files", "-z", "--", *(f":(glob)**/{m}" for m in BESIDE)],
                           capture_output=True, text=True, timeout=60)
        names = r.stdout.split("\0") if r.returncode == 0 else []
    except (OSError, subprocess.SubprocessError):
        names = []
    for name in filter(None, names):
        p = Path(name)
        found.add(tree / p.parent / BESIDE[p.name])
    return sorted(p for p in found if p.is_dir() and not p.is_symlink())


_API = None


def _api():
    """CoreFoundation and CoreServices through ctypes, loaded once; None where they cannot be loaded."""
    global _API
    if _API is None:
        try:
            cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
            cs = ctypes.CDLL(ctypes.util.find_library("CoreServices"))
            cf.CFURLCreateFromFileSystemRepresentation.restype = ctypes.c_void_p
            cf.CFURLCreateFromFileSystemRepresentation.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long,
                                                                   ctypes.c_bool]
            cf.CFRelease.argtypes = [ctypes.c_void_p]
            cs.CSBackupSetItemExcluded.restype = ctypes.c_int32
            cs.CSBackupSetItemExcluded.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_bool]
            _API = (cf, cs)
        except (OSError, AttributeError, TypeError):
            _API = False
    return _API or None


def mark(paths: list[str]) -> list[str]:
    """Give each folder a sticky Time Machine exclusion; returns the ones that could not be marked through the API."""
    api = _api()
    if api is None:
        return paths
    cf, cs = api
    left = []
    for p in paths:
        b = os.fsencode(p)
        url = cf.CFURLCreateFromFileSystemRepresentation(None, b, len(b), True)
        if not url:
            left.append(p)
            continue
        try:
            if cs.CSBackupSetItemExcluded(url, True, False) != 0:
                left.append(p)
        finally:
            cf.CFRelease(url)
    return left


def exclude(paths: Iterable[Path]) -> int:
    """Mark each folder (sticky; `mark`, then `tmutil addexclusion` for any the API refused, a batch per call); returns
    how many were given. Best effort: Time Machine's answer never stops the caller. Nothing to do on other systems."""
    paths = [str(p) for p in paths]
    if not paths or platform.system() != "Darwin":
        return 0
    left = mark(paths)
    for i in range(0, len(left), BATCH):
        try:
            subprocess.run(["tmutil", "addexclusion", *left[i:i + BATCH]], capture_output=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            return len(paths) - len(left) + i
    return len(paths)


def team_paths(root: Path, repo: Path) -> list[Path]:
    """What a team keeps out of Time Machine: its land trees whole, and the build output of every other worktree of
    the repo under its root (work order, lane and lead trees). A worktree outside the root is another team's."""
    root = Path(root).resolve()
    land = root / "land"
    paths = [land / d for d in LAND_TREES if (land / d).is_dir()]
    try:
        r = subprocess.run(["git", "-C", str(repo), "worktree", "list", "--porcelain"], capture_output=True, text=True,
                           timeout=60)
        lines = r.stdout.splitlines() if r.returncode == 0 else []
    except (OSError, subprocess.SubprocessError):
        lines = []
    for line in lines:
        if not line.startswith("worktree "):
            continue
        tree = Path(line[len("worktree "):])
        try:
            rp = tree.resolve()
        except OSError:
            continue
        if not str(rp).startswith(str(root) + "/") or str(rp).startswith(str(land) + "/") or not rp.is_dir():
            continue
        paths.extend(build_dirs(tree))
    return paths


def exclude_team(root: Path, repo: Path) -> int:
    """Mark every land tree and every work tree's build output of the team at root; returns how many were given."""
    return exclude(team_paths(root, repo))
