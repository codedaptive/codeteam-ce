"""Read one work order record for codeteam-land's idle clean (D597, D599).

A retired record is not read: wo-retire unregisters and removes its tree first, so there is nothing left to clean.
"""
import json
from pathlib import Path


def idle_record(path: Path) -> dict | None:
    """The record at `path`, or None when it is a `.retired.json` record, is gone since the listing (landed or
    retired meanwhile), or is half written (D442)."""
    if path.name.endswith(".retired.json"):
        return None
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return None
