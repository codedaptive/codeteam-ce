"""walls_owns: the owned paths a lane's walls line names in its role text (D567).

A lane with 12 or fewer owned entries gets each one, in order. A longer list collapses the files of any folder holding
more than 3 owned files into one item that names the folder, the count and the manifest: a lane owning hundreds of
test files would otherwise carry them all in every session's context. The text only tells the lane what it owns; the
zone guard enforces the walls from the manifest, so nothing is lost by the summary.
"""
from collections import Counter
from pathlib import PurePosixPath

LIST_ALL_UP_TO = 12     # entries; a list this short renders whole
CROWDED_OVER = 3        # files in one folder; more than this collapses into one item


def _is_file(entry: str) -> bool:
    # Told from the text, not the disk, so the render does not depend on the lane's tree; a glob or an entry ending
    # in "/" is never a file (PurePosixPath drops the slash, so `src/v1.2/` would otherwise have a suffix).
    return bool(PurePosixPath(entry).suffix) and not entry.endswith("/") and not any(c in entry for c in "*?[")


def walls_owns(owns: list[str], manifest) -> str:
    """The owned entries as backticked items joined with ", ", with crowded folders collapsed past 12 entries."""
    if len(owns) <= LIST_ALL_UP_TO:
        return ", ".join(f"`{x}`" for x in owns)
    folder = {x: str(PurePosixPath(x).parent) for x in owns if _is_file(x)}
    counts = Counter(folder.values())
    items, done = [], set()
    for x in owns:
        parent = folder.get(x)
        if parent is None or counts[parent] <= CROWDED_OVER:
            items.append(f"`{x}`")
        elif parent not in done:
            done.add(parent)
            items.append(f"`{parent}/`: {counts[parent]} files (the lane's `owns` in {manifest})")
    return ", ".join(items)
