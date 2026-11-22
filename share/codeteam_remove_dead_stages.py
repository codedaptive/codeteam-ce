"""Remove the admission records of stage runs whose process is gone; codeteam-land's stage_admit calls it under the
restart lock before it records its own run. A record that is not a valid admission (codeteam_stage_row) is left as
it is.
"""
from collections.abc import Callable
from pathlib import Path

from codeteam_stage_row import stage_row


def remove_dead_stages(stages: Path, alive: Callable[[int], bool]) -> None:
    """Unlink each stages/*.json record whose pid alive says is not running."""
    for path in stages.glob("*.json"):
        try:
            row = stage_row(path.read_text())
        except FileNotFoundError:
            continue                    # A stage may finish during the scan.
        if row is not None and not alive(row["pid"]):
            path.unlink(missing_ok=True)
