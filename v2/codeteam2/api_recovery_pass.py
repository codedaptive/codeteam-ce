"""The loop's recovery nudge: `continue` to a session whose turn ended on an API error the service has
since got past.

With D611's retry budgets a turn ends on its API error within minutes instead of waiting out an hour, and the
session then sits idle. Once a model request succeeds anywhere on the machine after that error (newest_success),
the session gets `continue` typed, once per error record (its uuid), only while it is idle or done and its screen
holds nothing. Every nudge goes through watch_record.

`continue` is typed through rt.transport.deliver, not Runtime.deliver: it is no stored mail.
"""
from .herdr import HerdrError
from .last_api_error import last_api_error
from .newest_success import newest_success
from .transcript_records import transcript_records
from .transport import Refused
from .watch_record import watch_record

EVERY_S = 30    # transcripts are re-read at most this often; an outage lasts minutes, so 30 s is prompt


def api_recovery_pass(rt, status, st, now: float, root=None) -> None:
    meta = st.setdefault("_apirecovery", {})
    if now - (meta.get("at") or 0) < EVERY_S:
        return
    meta["at"] = now
    nudged = meta.setdefault("nudged", {})
    episodes = list(_open_episodes(rt, status, st, nudged))
    if not episodes:
        return
    success = newest_success(min(at for _, (_, at, _) in episodes), root)
    for s, error in episodes:
        if success is not None and success > error[1] and rt.screen_hold(s, st) is None:
            _nudge(rt, s, nudged, error, success, now)


def _open_episodes(rt, status, st, nudged):
    """(session, (kind, at, uuid)) for each idle or done session whose last turn ended on a recoverable API error
    not yet nudged."""
    from .scheduler import READY    # here, not at the top: scheduler imports this module
    for s in rt.team.sessions():
        if status.get(s.key) not in READY:
            continue
        path = rt.transcript(st.setdefault(s.key, {}))
        error = last_api_error(transcript_records(path)) if path else None
        if error and nudged.get(s.key) != error[2]:
            yield s, error


def _nudge(rt, s, nudged, error, success, now):
    kind, at, uuid = error
    nudged[s.key] = uuid        # once per episode, even when the typing fails
    try:
        rt.transport.deliver(s.agent, "continue")
    except (Refused, HerdrError) as e:
        rt.log(f"api recovery {s.display}: continue failed: {type(e).__name__}: {e}")
        return
    watch_record(rt.team.dir, rt.log, {"at": now, "session": s.display, "agent": None, "error": kind,
                                       "error_at": at, "success_at": success, "wait_s": int(now - at),
                                       "action": "continue after api error", "error_record": uuid})
