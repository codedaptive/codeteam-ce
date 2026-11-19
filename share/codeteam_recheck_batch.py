"""Which pending Stage 5 recheck rows run together as one recheck.

"Testing is batched at integration. Integration and validation runs cover a group, never one landing at a time by
habit." So the recheck runner takes every pending row of land/recheck.jsonl at once and runs one recheck at the
newest row's landing commit M*. A row is pending while it has no "done". A pending migration move row ("move") is
still taken alone and first. A pending row whose M is neither M* nor an ancestor of it waits for a later batch.
"""

from collections.abc import Callable


def recheck_batch(rows: list[dict], contains: Callable[[str, str], bool]) -> list[int]:
    """The indexes of the rows the next recheck runs, in file order: the first pending move row alone; else every
    pending row whose M equals the newest pending row's M or is contained in it (contains(newest, M), never called
    for an equal M); [] when nothing is pending."""
    pending = [i for i, row in enumerate(rows) if "done" not in row]
    move = next((i for i in pending if rows[i].get("move")), None)
    if move is not None:
        return [move]
    if not pending:
        return []
    newest = rows[pending[-1]]["M"]
    return [i for i in pending if rows[i]["M"] == newest or contains(newest, rows[i]["M"])]
