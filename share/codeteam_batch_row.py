"""One Stage 5 recheck row standing for a batch of rechecks.

The batch rule: "Integration and validation runs cover a group, never one landing at a time by habit." The recheck runner
runs one recheck for a batch of pending rows (codeteam_recheck_batch), so it needs one row to run: the newest row's
time, landing commit M and work order, and the unions of every row's overlapping work orders, files, zones and sets,
so the recheck's steps reach everything any landing of the batch reached. "batch" names each row's work order for
the result line in integration-results.jsonl.
"""


def _union(lists) -> list:
    return list(dict.fromkeys(item for items in lists for item in items))


def batch_row(rows: list[dict]) -> dict:
    """The batch's row: "time", "M" and "wo" of the last row; "overlapping", "files" and "set" (each row's "set", or
    its "wo") as unions in row order; "zones" as a sorted union; "batch" as each row's "wo"."""
    newest = rows[-1]
    return {"time": newest["time"], "M": newest["M"], "wo": newest["wo"],
            "overlapping": _union(row["overlapping"] for row in rows),
            "zones": sorted(_union(row["zones"] for row in rows)),
            "files": _union(row.get("files", []) for row in rows),
            "set": _union(row.get("set") or [row["wo"]] for row in rows),
            "batch": [row["wo"] for row in rows]}
