"""When a work order tree was last used, for codeteam-land's idle clean, and which mark its record keeps.

A landed tree's age does not matter: it is cleaned once, as soon as nobody is inside, so it reports 0. An open tree
reports its newest commit, or its newest edit when that is later. Its edits come from `git status` (the files git
sees as changed; ignored build output excluded), never a walk of the tree (2026-11-08: migrated
request trees took 3 h 20 min to walk and held every landing), and status runs only once the last commit is past
the limit, since a newer commit already makes the tree active.
"""
from collections.abc import Callable
from pathlib import Path

STATUS_LINES = 5000     # a tree with more changed files than this is judged by the first ones git lists


def idle_tree_activity(tree: Path, landed: bool, limit: float, now: float,
                       git: Callable) -> tuple[str, float | None, str | None]:
    """(mark, last active in epoch seconds, error). `mark` is the record field the clean writes: `landed_cleaned`
    for a `landed` tree, `cleaned` for an open one. A landed tree without .git (wo-retire removed the work tree)
    gives (mark, None, None): nothing to clean and nothing to report. An open tree where `git log` fails gives
    (mark, None, git's error text, stripped). `git(tree, *args, check=False)` is codeteam-land's git."""
    if landed:
        return "landed_cleaned", (0.0 if (tree / ".git").exists() else None), None
    head = git(tree, "log", "-1", "--format=%ct", check=False)
    if head.returncode:
        return "cleaned", None, (head.stderr or head.stdout).strip()
    last = float(head.stdout.strip() or 0)
    if now - last <= limit:
        return "cleaned", last, None
    status = git(tree, "status", "--porcelain", "--untracked-files=all", check=False)
    for line in status.stdout.splitlines()[:STATUS_LINES]:
        try:
            last = max(last, (tree / line[3:].split(" -> ")[-1].strip('"')).stat().st_mtime)
        except OSError:          # changed and gone, or unreadable: counts as used now
            last = now
    return "cleaned", last, None
