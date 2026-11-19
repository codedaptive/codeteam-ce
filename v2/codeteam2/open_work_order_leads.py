"""A lane's open work orders whose trees show a lead at work, counted by the patrol as running leads (D590)."""
from pathlib import Path


def open_work_order_leads(t, lane, records, skip, now) -> list[str]:
    """The "wo" names of lane's open work-order records (work_order_records) whose tree is live: someone inside it, or
    activity within v1.PATROL_DEAD_MIN, the measures v1.lane_work uses. Left out: other lanes' records (before any
    tree is measured), queued or held ones, a missing tree, a tree in skip (resolved paths an active ledger row
    already counts), and one the landing tool holds (v1._landing_holds). The landing tool's own docs- and revert-
    orders count like any other: a live tree is a lead at work. A tree named by two records counts once.
    t: v1's team."""
    from .team import v1
    out, seen = [], set(skip)
    for rec in records:
        if rec["zone"] != lane or rec.get("queued") or rec.get("held"):
            continue
        tree = Path(rec["tree"])
        if not tree.is_dir() or tree.resolve() in seen or v1._landing_holds(t, tree):
            continue
        if v1._someone_inside(tree) or now - v1._last_activity(tree) < v1.PATROL_DEAD_MIN * 60:
            seen.add(tree.resolve())
            out.append(rec["wo"])
    return out
