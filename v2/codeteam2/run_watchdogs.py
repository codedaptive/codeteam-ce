"""The loop's watchdogs on each tick: the hung-request watch, then the API-error recovery."""
from .api_recovery_pass import api_recovery_pass
from .hang_watch_pass import hang_watch_pass


def run_watchdogs(rt, status, st, now: float) -> None:
    """Run hang_watch_pass, then api_recovery_pass, unless the team is going down or halted. Both passes type
    into sessions (Esc, continue), so a team being ended or halted gets neither. A pass that raises is logged and
    the next still runs: a watchdog must never stop the loop."""
    if (rt.team.dir / "down").exists() or getattr(rt.team, "halted", lambda: False)():
        return
    try:
        hang_watch_pass(rt, status, st, now)
    except Exception as e:
        rt.log(f"hangwatch skipped: {type(e).__name__}: {e}")
    try:
        api_recovery_pass(rt, status, st, now)
    except Exception as e:
        rt.log(f"api recovery skipped: {type(e).__name__}: {e}")
