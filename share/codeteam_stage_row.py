"""One stage admission record (restart/stages/*.json) read from its text, for codeteam-land's stage_holders and
codeteam_remove_dead_stages. A record cut short by a crash, or not an object with a whole-number pid, is no admission:
the readers skip it rather than fail the admission that scans it.
"""
import json


def stage_row(text: str) -> dict | None:
    """The parsed record when text is a JSON object whose pid is an int (not a bool), else None."""
    try:
        row = json.loads(text)
    except ValueError:
        return None
    if not isinstance(row, dict) or type(row.get("pid")) is not int:
        return None
    return row
