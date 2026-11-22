"""What the watchdog does about a pending model request.

A main session is nudged (Esc, then `continue`) at its model's threshold: that costs one re-sent request and loses
no work. A subagent can only be stopped and started again by its parent, which loses the helper's context, so its
parent is told only at twice the threshold.
"""
from .threshold_s import threshold_s

MULTIPLE = {"main": (1, "nudge"), "subagent": (2, "note")}


def hang_action(kind: str, pending, now: float, overrides=None) -> str | None:
    """"nudge" (kind "main") or "note" (kind "subagent") once `pending` has waited long enough, else None."""
    if not pending:
        return None
    times, action = MULTIPLE[kind]
    return action if now - pending["at"] >= times * threshold_s(pending["model"], overrides) else None
