"""Whether a landed commit is already in any of the given tips (D563).

A work order that merged a landing before Stage 2 tested that landing's lines with its own, so the landing is no
overlap for its recheck or its conflict report.
"""
from collections.abc import Iterable


def merged_landing(git, commit: str, tips: Iterable[str]) -> bool:
    """True when `commit` is an ancestor of (or equal to) any tip, tried in order. `git(*args)` returns an object
    with .returncode; an exception it raises propagates."""
    for tip in tips:
        if git("merge-base", "--is-ancestor", commit, tip).returncode == 0:
            return True
    return False
