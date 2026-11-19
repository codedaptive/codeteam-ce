"""Which row of a Stage 5 recheck batch a failing test is attributed to.

The batch rule: "A failure in a batch is sent back to the zone that owns the failing code ... the rest of the batch stands."
A batched recheck opens one finding per failing test, owned by the newest row whose landing reached the failing
step's zone; when no row reached it, or the step names no zone, the newest row owns it.
"""


def batch_owner(rows: list[dict], zone: str | None) -> dict:
    """The last row whose "zones" holds zone; else, or when zone is None, the last row."""
    return next((row for row in reversed(rows) if zone is not None and zone in row["zones"]), rows[-1])
