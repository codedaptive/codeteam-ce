"""detached_wo_branches: the branches of open work orders whose trees the landing tool has on a detached HEAD.

codeteam-land's check of a landing set (merge_set_tips) detaches the first member's tree onto the members' merged
tips for the whole of Stage 2, then checks its branch out again. On widgets that takes an hour or more. Meanwhile git
lists the tree with no branch, so the branch audit counted the open work order's branch as checked out nowhere and
flagged it on every patrol. The landing tool's own record of an open work order names its
tree and branch, so a detached tree is matched to its branch by that record, never by its folder's name.
"""
import json
import os
from pathlib import Path


def detached_wo_branches(wo_dir: Path, porcelain: list[str]) -> set[str]:
    """Branches named by open work order records in wo_dir (<wo>.json with no <wo>.landed.json or <wo>.retired.json)
    whose recorded tree `git worktree list --porcelain` (its lines, porcelain) shows on a detached HEAD. A record that
    cannot be read is skipped."""
    detached, tree = set(), None
    for line in porcelain:
        if line.startswith("worktree "):
            tree = line[len("worktree "):]
        elif line == "detached" and tree:
            detached.add(os.path.realpath(tree))
    if not detached:
        return set()
    branches = set()
    for path in Path(wo_dir).glob("*.json"):
        wo = path.name[:-len(".json")]
        if "." in wo or (path.parent / f"{wo}.landed.json").exists() or (path.parent / f"{wo}.retired.json").exists():
            continue
        try:
            rec = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict) and rec.get("branch") and rec.get("tree") \
                and os.path.realpath(str(rec["tree"])) in detached:
            branches.add(str(rec["branch"]))
    return branches
