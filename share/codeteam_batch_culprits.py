"""Which batch entries a failure's frames point at.

The batch rule: "A failure in a batch is sent back to the zone that owns the failing code, by file and line." A frame
matches an entry when the entry changed its file and either the frame has no line (a CodeGraph callee), the entry
deleted the file, the line is inside one of the entry's changed ranges, or another entry changed the same file too:
the batch tree merges every entry, so its line numbers are shifted by the others' hunks and only the file is sure.
"""

from collections import Counter


def _matches(path: str, line: int | None, ranges: dict[str, list[tuple[int, int]]], shared: int) -> bool:
    """The entry with ranges changed path, and the frame's line is unknown or inside its ranges, or its file is
    shared or deleted (shared: how many entries changed path)."""
    if path not in ranges:
        return False
    return line is None or shared > 1 or not ranges[path] or any(start <= line <= end for start, end in ranges[path])


def batch_culprits(frames: list[list], changes: dict[str, dict[str, list[tuple[int, int]]]]) -> dict[str, list[list]]:
    """{entry key: its matched frames} for the entries of changes (key -> diff_ranges) that any frame matches, in
    changes' order, each entry's frames in their given order."""
    shared = Counter(path for ranges in changes.values() for path in ranges)
    culprits = {}
    for key, ranges in changes.items():
        matched = [[path, line] for path, line in frames if _matches(path, line, ranges, shared[path])]
        if matched:
            culprits[key] = matched
    return culprits
