"""Which item of a relative `make DIR=` the zone guard refuses.

lab's lab Makefile runs `make zone-test-one DIR=tests.test_x`, and takes a comma
list of such names as one process per module, so a DIR of dotted
names is judged by the module file each name stands for; any other DIR by its own path.
"""
import os
from collections.abc import Callable
from pathlib import Path


def make_dir_refusal(d: str, base: str, root: str, in_zone: Callable[[str], bool]) -> str | None:
    """The first item of a relative DIR outside the zone, or naming no module file; None when every one is in it."""
    for item, f in _paths(d, base):
        if f is None or not in_zone(os.path.relpath(os.path.realpath(f), root)):
            return item
    return None


def _paths(d: str, base: str) -> list[tuple[str, Path | None]]:
    """Return the (item, path) pairs to judge for a relative DIR under base.

    A DIR with no '/' that is no path under base and whose comma items are all dotted
    Python names (two or more identifier parts) gives one pair per item: its module
    file base/p1/.../pk.py for the longest prefix p1..pk that is a file (a trailing class
    or test name is not part of the path), or None when no prefix is one. Any other DIR
    gives the one pair (DIR, base/DIR).
    """
    path = Path(base) / d
    items = d.split(",")
    parts = [item.split(".") for item in items]
    if "/" in d or path.exists() or not all(
            len(p) >= 2 and all(s.isidentifier() for s in p) for p in parts):
        return [(d, path)]
    return [(item, _module_file(p, Path(base))) for item, p in zip(items, parts)]


def _module_file(parts: list[str], base: Path) -> Path | None:
    for k in range(len(parts), 0, -1):
        f = base.joinpath(*parts[:k - 1], parts[k - 1] + ".py")
        if f.is_file():
            return f
    return None
