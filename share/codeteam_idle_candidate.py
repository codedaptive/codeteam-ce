"""Whether the landing runner's idle clean takes a work order tree (D597, D599).

Nothing is taken while a process works inside the tree (a Stage 2 step, a build or a lead's own command; the caller
measures it, and a request lead between commands is not seen) or while it holds nothing zone-clean removes. A landed work order's tree is taken once, as soon as both hold, whatever its age; its clean mark
keeps it from being taken again. An open tree is taken when it has been idle past the limit. An open tree it cleaned
is taken again only once it has been used after that clean: a lead that came back rebuilt its output and index, and
they are worth freeing when it goes idle again; a tree nobody touched since keeps what was recreated in it, such as
an index seeded again by a query. codeteam-land's clean_idle calls this, so it stays a function of its arguments.
"""
import datetime as dt


def idle_candidate(last_active: float, now: float, limit: float, holds: bool, cleaned: str | None, inside: bool,
                   landed: bool) -> bool:
    """False when `inside` (a process works in the tree) or the tree does not hold (`holds`) cleanable folders. A `landed`
    tree is taken when it has no clean mark. An open one is taken when `now - last_active` (epoch seconds) exceeds
    `limit` and it has no clean mark or was last active after it. `cleaned` is the ISO-8601 time with UTC offset that
    codeteam-land's now() writes; an empty mark counts as none."""
    if inside or not holds:
        return False
    if landed:
        return not cleaned
    if now - last_active <= limit:
        return False
    return not cleaned or last_active > dt.datetime.fromisoformat(cleaned).timestamp()
