"""Clean one idle or landed work order tree with `make zone-clean` and measure what it freed.

codeteam-land's clean_idle calls this for each tree idle_candidate takes, with an environment that carries no
ZONE_CLEAN_KEEP_INDEX, so the index goes too; the bytes freed go in its log line and its total. The size is du's
over the fixed folder names, never a Python walk of the tree (walking acme's request trees took hours).
"""
import subprocess
from pathlib import Path

# What zone-clean removes: zone/zone.mk's default CLEAN_DIRS plus .codegraph, so keep the two in step. node_modules
# is not here: zone-clean leaves it, so a tree holding only node_modules has nothing to clean.
CLEANED_DIRS = ("cargo-target", "target", ".build", ".codegraph")


def _size(tree: Path) -> int:
    """Bytes in the CLEANED_DIRS present in `tree`, from `du -sk`; 0 when none is."""
    present = [d for d in CLEANED_DIRS if (tree / d).exists()]
    if not present:
        return 0
    du = subprocess.run(["du", "-sk", *present], cwd=tree, capture_output=True, text=True)
    return sum(int(line.split()[0]) for line in du.stdout.splitlines() if line.split()) * 1024


def clean_idle_tree(tree: Path, env: dict) -> int:
    """Run `make --no-print-directory zone-clean` in `tree` with `env` (output captured) and return the bytes it
    freed from the CLEANED_DIRS, never negative."""
    before = _size(tree)
    subprocess.run(["make", "--no-print-directory", "zone-clean"], cwd=tree, env=env, capture_output=True)
    return max(0, before - _size(tree))
