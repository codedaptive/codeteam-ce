"""reported_repeat: the slow-tests follow-up whose landed report already covers a new flag.

the slow-test rule opens one follow-up for the zone owning a slow landing's slowest tests, to find why and write it up. A follow-up
closes when its report lands, so the zone's next slow landing opened another for the same tests while the fix the
report ordered had not promoted yet: acme's WidgetCoreKit got slow#5, #6 and #7 within 90 minutes for the same import
test and unit-bundle build, each costing a lane turn, a report tree, a Stage 2 run and a Kong review.
A flag whose zone and slowest step match a follow-up closed by a landed report within REPEAT_HOURS is recorded on that
follow-up instead; the flag itself still goes on the landing and to the orchestrator."""
from datetime import datetime

REPEAT_HOURS = 24


def reported_repeat(items: list[dict], zone: str, step: str, when: str, hours: float = REPEAT_HOURS) -> dict | None:
    """The newest follow-up of `zone` closed by a landed report (not dropped) within `hours` before `when` whose slowest
    step is `step`; None when there is none or the times cannot be read."""
    try:
        at = datetime.fromisoformat(when)
    except (TypeError, ValueError):
        return None
    best = None
    for item in items:
        steps = item.get("steps") or []
        if (item.get("zone") != zone or item.get("state") != "closed" or not item.get("closed_by")
                or not steps or steps[0].get("step") != step):
            continue
        try:
            closed = datetime.fromisoformat(item["closed"])
            age = (at - closed).total_seconds()
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= age <= hours * 3600 and (best is None or closed > best[0]):
            best = (closed, item)
    return best[1] if best else None
