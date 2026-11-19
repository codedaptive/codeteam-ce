"""Record on a queue entry the integration run its test moves owe.

A test moved into integration is not code, but it has not run in its new group yet: the entry owes an integration
run, names the moved file, and names the zone that owns it. A move into validation or unit owes nothing here.
"""
from collections.abc import Callable


def owe_test_moves(entry: dict, moves: list[dict], zone_of: Callable[[str], str]) -> None:
    """Mark `entry` as owing integration for each move into integration, in place: its path appended to "files" and
    zone_of(path) added to "zones" (both without duplicates; zones kept sorted, as queue_entry sorts them)."""
    for move in moves:
        if move["group"] != "integration":
            continue
        entry["integration"] = "owed"
        files = entry.setdefault("files", [])
        if move["path"] not in files:
            files.append(move["path"])
        entry["zones"] = sorted(set(entry.get("zones", [])) | {zone_of(move["path"])})
