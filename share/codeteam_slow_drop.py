"""Drop a slow-tests follow-up judged not real.

A follow-up opened on a wrong measure (widgets's lock waits counted as run time) has no slowness to
report on. `codeteam-land finding-drop slow#N --reason` drops it as finding-drop drops a finding: the entry stays in
slow-tests.json, marked dropped, so the zone is free for its next follow-up and --fixes can no longer name it.
"""


def drop_slow(items: list[dict], fid: str, reason: str, by: str, when: str) -> list[dict] | None:
    """`items` with the open follow-up `fid` marked dropped, with the reason, the time and who dropped it; None when
    no follow-up `fid` is open."""
    item = next((x for x in items if x.get("id") == fid and x.get("state") == "open"), None)
    if item is None:
        return None
    item.update(state="dropped", closed=when, reason=reason, dropped_by=by)
    return items
