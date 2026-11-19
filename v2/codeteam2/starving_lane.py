"""A lane starved at the lane cap.

At the cap the swap ends an idle lane to make room, but it leaves a lane whose /exit was cancelled for background work
(Runtime.confirm_exit: a run, a build or its own land matters more than its slot). A stuck background command looks the
same as real work, so widgets's Coord-sync waited 17 hours behind a two-day-old `rg` in Coord-tools with nobody told.
This names that case to the team's orchestrator, which can have the lane stop stale work.
"""

# Long enough that a lane waiting behind real work, which frees its slot within a swap round or two, is not reported.
STARVE_ALERT_MIN = 60


def starving_lane(waiting, acts, awake, st, now, swapping=False, alert_min=STARVE_ALERT_MIN):
    """[("starve", key, minutes, holders)] for the lane that has waited longest for a slot, or [].

    waiting: [(since, key)] oldest first, the lanes waiting to start; acts: plan's actions so far (a lane it starts is
    not waiting); awake: the lanes holding slots; st: key -> state record; swapping: plan is ending a lane to make room
    this tick, so a slot is coming. It fires when the oldest waiting lane has waited alert_min and at least one awake
    lane is in its hold after a cancelled exit (bg_until), and once per wait: the lane's start clears starve_alerted.
    holders are those awake lanes, sorted."""
    if swapping or not waiting:
        return []
    since, key = waiting[0]
    if ("start", key) in acts or st.get(key, {}).get("starve_alerted"):
        return []
    mins = (now - since) / 60
    holders = tuple(sorted(v for v in awake if (st.get(v, {}).get("bg_until") or 0) > now))
    if mins < alert_min or not holders:
        return []
    return [("starve", key, int(mins), holders)]
