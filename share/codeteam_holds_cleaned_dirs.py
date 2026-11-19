"""Whether a work order tree holds anything zone-clean removes, for codeteam-land's idle clean (D597, D599).

The check is a stat of each fixed folder name, never a walk of the tree (problem 27), so a tree with nothing to clean
costs no git call and no du.
"""
from pathlib import Path

from codeteam_clean_idle_tree import CLEANED_DIRS


def holds_cleaned_dirs(tree: Path) -> bool:
    """True when one of CLEANED_DIRS exists in `tree`; False for a tree that is gone."""
    return any((tree / d).exists() for d in CLEANED_DIRS)
