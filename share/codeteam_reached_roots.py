"""Which of a reached zone's test roots a change reaches.

A zone is reached when a changed file is in the scope of one of its packages, but most zones own several test roots
and only some depend on the change: widgets's zones each own a crate and its folders under the test crate. A reached
zone runs only the roots whose own dependency scope (zone-tool's scope_dirs) holds a changed file. A scope entry
"a!b" is folder a without its child b (a Swift package's own Rust port, which has a root of its own).
"""
from collections.abc import Callable
from fnmatch import fnmatchcase


def _holds(entry: str, path: str) -> bool:
    base, *left_out = entry.split("!")
    if base in (".", ""):
        return True

    def under(folder):
        return path == folder or path.startswith(folder + "/")
    inside = fnmatchcase(path, base) if any(ch in base for ch in "*?[") else under(base)
    return inside and not any(under(f"{base}/{child}") for child in left_out)


def doc_entries(root: str, entries: list[str] | None, is_package: Callable[[str], bool]) -> list[str] | None:
    """The part of root's scope a document reaches it through: the root's own folder and every
    entry that is not another package (a folder its sources read by path, the test runner's scripts). A document
    inside a package the root depends on is that package's, not the root's (a document beside code must not
    widen the run; a crate's doc tests read its own README). None, the whole tree, stays None."""
    if entries is None:
        return None
    own = root.strip("/")
    keep = []
    for entry in entries:
        base = entry.split("!")[0]
        if base == own or base.startswith(own + "/") or not is_package(base):
            keep.append(entry)
    return keep


def reached_roots(roots: list[str], files: list[str], scope: Callable[[str], list[str] | None]) -> list[str]:
    """The roots, in their order, whose scope holds a file in `files`. scope(root) is the root's scope_dirs list;
    None is the whole tree, which holds every file. No files: none."""
    if not files:
        return []
    reached = []
    for root in roots:
        entries = scope(root)
        if entries is None or any(_holds(entry, path) for entry in entries for path in files):
            reached.append(root)
    return reached
