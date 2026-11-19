"""Which standing trees an idle-ended session's clean may touch (D598).

A lane ended for being idle holds its build output on disk until something cleans it; this picks the trees to
clean. Pure, so the choice is tested without git, files or the build queue: the caller says which trees are git
trees and which worktrees have a running build. A tree with a running build in it, or in a worktree nested inside
it (a request tree under .claude/worktrees), is left alone: zone-clean would pull its output from under the build.
Paths are compared after os.path.normpath only, never resolved, so no filesystem call is made.
"""
import os
from collections.abc import Iterable
from pathlib import Path


def idle_clean_trees(kind: str, trees: Iterable[tuple[Path, bool]], busy: Iterable[str | Path]) -> list[Path]:
    """The git trees of a lane to clean, in input order without duplicates, minus those holding a running build."""
    if kind != "lane":
        return []
    busy_paths = [os.path.normpath(b) for b in busy]
    chosen: list[Path] = []
    for tree, is_git in trees:
        root = os.path.normpath(tree)
        if not is_git or Path(root) in chosen:
            continue
        if any(b == root or b.startswith(root.rstrip(os.sep) + os.sep) for b in busy_paths):
            continue
        chosen.append(Path(root))
    return chosen
