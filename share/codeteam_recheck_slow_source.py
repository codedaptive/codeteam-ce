"""What the slow-tests report says about a Stage 5 recheck.

The batch rule runs one recheck for a batch of landings, so its slow-tests report is made once for the batch: the head names
every work order of the batch and its M, and the follow-up's source is row["wo"] with its own landed zone
(recheck_slow_report passes the newest work order whose Stage 2 was over the limit; the routing sends the follow-up to
that zone when the slowest step's zone holds no file the landings changed).
"""

from collections.abc import Callable


def recheck_slow_source(row: dict, landed: Callable[[str], dict | None]) -> tuple[str, dict]:
    """(head, source) for report_slow_tests: "<wos> recheck at M <M[:10]>", with wos row["batch"] or [row["wo"]], and
    {"wo", "zone" (landed(wo)'s, or None), "stage": 5, "commit": M}."""
    head = f"{', '.join(row.get('batch') or [row['wo']])} recheck at M {row['M'][:10]}"
    return head, {"wo": row["wo"], "zone": (landed(row["wo"]) or {}).get("zone"), "stage": 5, "commit": row["M"]}
