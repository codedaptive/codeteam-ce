"""TEAM IDLE WITH WORK: the patrol line for a whole team stopped with open work (2026-11-15).

Sprocket lost 7 hours (04:43-11:36) to a squash held for a ruling that never reached its designer while its orchestrator
was stuck. Every patrol line goes to the orchestrator, so when the orchestrator is the stuck one nobody else hears. This
line wakes the orchestrator and, through the scheduler, tells the owner as well. It is new once per episode: it names the time
of the team's last work, which stays the same until a session works again.
"""
import json
import time
from pathlib import Path

IDLE_MIN = 60                   # no session of the team has worked for this long
QUIET = ("idle", "done", "absent")


def _open_work(land_dir, held=frozenset()):
    """(work orders open and not queued, queued landings held by land-hold), from the landing tool's records. The
    landing tool's own docs- and revert- work orders are left out, as stalled_work_orders does, and so is a work order
    whose zone the user holds (team/held/<lane>): that lane is stopped on purpose. A held landing still counts:
    the landing tool runs it, not the lane."""
    land = Path(land_dir)
    orders = 0
    for f in land.glob("wo/*.json"):
        if f.name.endswith((".landed.json", ".retired.json")):
            continue
        try:
            rec = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if (not rec.get("queued") and rec.get("zone") not in held
                and not str(rec.get("wo", f.stem)).startswith(("docs-", "revert-"))):
            orders += 1
    holds = 0
    for f in land.glob("queue/*.json"):
        try:
            holds += bool(json.loads(f.read_text()).get("hold"))
        except (OSError, ValueError):
            continue
    return orders, holds


def team_idle(status, st, now, land_dir, idle_min=IDLE_MIN, held=frozenset()):
    """The TEAM IDLE WITH WORK line, or None. status: session key -> herdr state; st: the loop's record per session.
    Idle means every session is idle, done or asleep, and the newest work of any of them (worked_at, which the loop
    sets while a session works or completes a turn; state_since for a session not seen working since that was added)
    is idle_min or more ago. Work means a work order open and not queued whose zone is not in held (the lanes the user
    holds), or a queued landing held. A blocked session is not idle: it has its own alert."""
    if not status or any(s not in QUIET for s in status.values()):
        return None
    last = max((st.get(k, {}).get("worked_at") or st.get(k, {}).get("state_since") or 0) for k in status)
    if not last or now - last < idle_min * 60:
        return None
    if not any(_open_work(land_dir, held)):
        return None
    # Only the episode's start goes in the line: patrol.record compares whole lines, and the counts of open work can
    # change while nobody works (the landing runner cuts a fix work order when a recheck or a validation fails), which
    # would make it new again (Kong).
    since = time.strftime("%m-%d %H:%M", time.localtime(last))
    return (f"TEAM IDLE WITH WORK: no session of this team has worked since {since} (over {idle_min} min) while a work "
            "order is open or a queued landing is held (codeteam-land queue; land/wo). Find what each waits on and "
            "send the next step; the owner is told too, once.")
