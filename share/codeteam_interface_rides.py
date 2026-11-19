"""Whether an "Interface change coming" notice to a zone rides along instead of waking its coordinator (D600)."""

from collections.abc import Callable, Iterable


def interface_rides(zone: str, callers: list[str] | None, records: Iterable[dict],
                    diff_of: Callable[[dict], list[str]]) -> bool:
    """True when no open work order of zone touches the changed symbol's callers there, so nothing in flight needs
    the notice now. A work order queued to land is not open. Unknown callers (None), or a diff that cannot be read,
    count as touching: the notice wakes."""
    considered = [r for r in records if r.get("zone") == zone and not r.get("queued")]
    if not considered:
        return True
    if callers is None:
        return False
    wanted = set(callers)
    for rec in considered:
        try:
            if wanted.intersection(diff_of(rec)):
                return False
        except Exception:               # an unreadable diff may touch the callers: wake
            return False
    return True
