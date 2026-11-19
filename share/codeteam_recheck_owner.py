"""Whom a new finding from a Stage 5 recheck is opened against.

The batch rule: "A failure in a batch is sent back to the zone that owns the failing code, by file and line; the rest of
the batch stands." So a batched recheck opens one finding per failing test, against the newest row of the batch whose
landing reached the failing step's zone, else the newest row (codeteam_batch_owner), at the batch's M. A migration
move row is rechecked alone and keeps its own owner: itself, under v54-move, in the failing test's validation zone.
"""

from collections.abc import Callable

from codeteam_batch_owner import batch_owner


def recheck_owner(rows: list[dict], row: dict, step_zone: Callable[[str], str | None],
                  landed: Callable[[str], dict | None],
                  validation_zone: Callable[[str], str]) -> Callable[[dict], tuple[dict, dict | None]]:
    """owner(test) -> (owner row, its landed record) for the recheck of rows run as row (row["M"] is the batch's M)."""
    if row.get("move"):
        return lambda test: (row, {"wo": "v54-move", "feature": "v54-move", "zone": validation_zone(test["name"])})

    def owner(test: dict) -> tuple[dict, dict | None]:
        owner_row = batch_owner(rows, step_zone(test["name"])) | {"M": row["M"]}
        return owner_row, landed(owner_row["wo"])
    return owner
