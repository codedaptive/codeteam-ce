"""order_trees: the work order trees under a team's worktree root, for the watchdog's disk sweeps.

Two sources, because neither alone sees every tree: the landing tool's open work order records (land/wo/*.json, each
naming its tree, which may live outside root/wo), and every root/wo/<lane>/<name> folder holding a .git entry, which
catches trees with no record (cancelled WorktreeCreate starts; 19-27 GB each in widgets). The
landing tool's own clones (land/itest, land/validate) are listed only when a record names them.
"""
import json
from pathlib import Path


def order_trees(root: Path) -> set[Path]:
    """The trees named by root/land/wo's records that are not landed or retired (a record that cannot be read or
    names no tree is skipped), plus every root/wo/*/* folder with a .git file or folder."""
    trees = set()
    for f in (root / "land" / "wo").glob("*.json"):
        if f.name.endswith((".landed.json", ".retired.json")):
            continue
        try:
            trees.add(Path(json.loads(f.read_text())["tree"]))
        except (OSError, ValueError, KeyError):
            continue
    return trees | {p for p in (root / "wo").glob("*/*") if p.is_dir() and (p / ".git").exists()}
