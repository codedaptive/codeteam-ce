"""The owned test files that lie in none of a lane's test roots (D507, Orc-Codeteam-jj #4441).

A lane may own test files by name or glob outside its folders, such as codeteam-jj's zone lane and its
tests/unit/land-*.py. Stage 2's unit evidence under CODETEAM_KINDS_BY_NAME=1 is the lead's record per test root, and no
root holds these files. So the landing tool asks this module whether such files exist, and when they do it takes the
lane's root run instead, which runs every owned test once.
"""
from collections.abc import Callable, Iterable
import glob
from pathlib import Path


def loose_owned_tests(tree: Path, owns: Iterable[str], roots: Iterable[str],
                      plan: Callable[[Path, str], list]) -> list[str]:
    """Each owns entry glob-expanded from tree, as zone-tool's root run expands it; of the matches, the files under
    none of roots for which plan(path, rel) lists a run (zone-tool's answer for an owned file in a unit run), sorted
    and once each. Folders are left to the roots."""
    inside = [r.strip("/") for r in roots if r.strip("/") not in ("", ".")]
    loose = set()
    for entry in owns:
        for rel in glob.glob(entry, root_dir=tree):
            if not (tree / rel).is_file() or any(rel == r or rel.startswith(r + "/") for r in inside):
                continue
            if plan(tree / rel, rel):
                loose.add(rel)
    return sorted(loose)
