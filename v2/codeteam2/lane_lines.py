"""The patrol's lines for one lane, from v1's reading of its ledger (`lane_work`), the lane's open work-order trees
(D590) and the lane's herdr state."""
from .open_work_order_leads import open_work_order_leads

READY = ("idle", "done")


def lane_lines(t, n, r, status, st, pending, now, idle_min, records=()) -> list[str]:
    """Lane n's patrol lines, in order: IDLE WITH WORK, DEAD LEAD, SERIAL, parked rows, ASLEEP WITH WORK. t: v1's team;
    r: the lane's manifest entry; status: key -> herdr state; st: the loop's state per session; pending: mail waiting
    per key; idle_min: minutes idle before a lane with work is named; records: the team's open work-order records
    (work_order_records). Running leads, which IDLE WITH WORK and SERIAL judge, are the ledger-active rows plus the
    lane's live work-order trees no active row names (open_work_order_leads, D590); those trees are measured only for
    an awake lane given records, the only case either line can fire."""
    from .team import v1
    rows, active, dead, parked, queued = v1.lane_work(t, n, r, now)
    if not rows:
        return []
    awake, quiet = _state(n, status, st, now)
    mailed = bool(pending.get(n))
    running = len(active)
    if records and awake:
        running += len(open_work_order_leads(t, n, records, _ledger_trees(t, n, rows, active), now))
    out = _idle(n, awake, quiet, idle_min, running, dead, queued, mailed)
    for d in dead:
        out.append(f"{n}: DEAD LEAD on {d}, its worktree untouched {v1.PATROL_DEAD_MIN}+ min and nothing running in it")
    out += _serial(n, awake, quiet, idle_min, running, queued)
    if parked:
        out.append(_parked(n, parked, v1.landing(t)))
    out += _asleep(n, awake, queued, mailed)
    return out


def _ledger_trees(t, n, rows, active) -> set:
    """The resolved trees of lane n's ledger-active rows ([name, stage, lead ids] each), found as v1.lane_work finds
    them (v1._lead_paths), so a work order already counted by its row is not counted again."""
    from .team import v1
    return {p.resolve() for name, _, wts in rows if name in active
            for p in v1._lead_paths(t, n, [w for w in wts.split(",") if w and w != "-"])}


def _state(n, status, st, now) -> tuple[bool, float]:
    s = status.get(n, "absent")
    quiet = (now - (st.get(n, {}).get("state_since") or now)) / 60 if s in READY else 0
    return s != "absent", quiet


def _idle(n, awake, quiet, idle_min, running, dead, queued, mailed) -> list[str]:
    if awake and quiet >= idle_min and not running and (queued or dead) and not mailed:
        return [f"{n}: IDLE WITH WORK, idle {quiet:.0f} min, {len(queued)} queued ({', '.join(queued[:3])})"]
    return []


def _serial(n, awake, quiet, idle_min, running, queued) -> list[str]:
    if awake and len(queued) >= 2 and running <= 1 and quiet < idle_min:
        return [f"{n}: SERIAL, {running} lead running and {len(queued)} queued ({', '.join(queued[:4])})"]
    return []


def _parked(n, parked, landing) -> str:
    # The patrol skips a waiting row by the stage words only on a landing team; elsewhere by an awaited
    # feature the stage names (lane_work).
    hint = ('stage it "waits for <what>"' if landing
            else 'await its feature and stage it "waiting <feature>"')
    return (f"{n}: {parked} ledger row(s) past queued with no live lead for a day or more; close or "
            f"requeue them (a row that waits on purpose: {hint}; a running lead's row names its tree)")


def _asleep(n, awake, queued, mailed) -> list[str]:
    if not awake and queued and not mailed:
        return [f"{n}: ASLEEP WITH WORK, {len(queued)} queued and no mail to wake it"]
    return []
