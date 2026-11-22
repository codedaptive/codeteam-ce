"""A test record file read as JSON; bin/zone-tool's print_done uses it for the build part of its summary line."""
import json
from pathlib import Path


def read_record_file(path) -> dict:
    """The record at path as parsed JSON, or {} when it is missing, unreadable, or there is no path (a job that wrote
    no record: zone-tool job wait raised TypeError on Path(None))."""
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
