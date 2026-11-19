"""Which ready queue entries queue-run takes next.

An entry `land` queued with "integration": "owed" still needs Stage 2's integration step, which queue-run runs once
for every such ready entry together. An entry without the mark was fully checked when it was queued and lands alone,
as Stage 4 always landed it, before any batch.
"""

from collections.abc import Hashable


def ready_batch(items: list[tuple[Hashable, dict]]) -> tuple[Hashable | None, list[Hashable]]:
    """items: (key, entry) in the order queue-run takes them (priority, then queue order; sorted by
    advance_queue, not here). Ready: not held and reviewed "land". (the first ready key without the owed
    mark, []) when there is one; else (None, every ready key, in input order)."""
    ready = [(key, entry) for key, entry in items if not entry.get("hold") and entry.get("review") == "land"]
    alone = next((key for key, entry in ready if entry.get("integration") != "owed"), None)
    if alone is not None:
        return alone, []
    return None, [key for key, _ in ready]
