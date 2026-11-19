"""Whose turn it is at a first-come, first-served lock (D592).

A ticket is (arrival time_ns, pid). The head is the oldest ticket whose process is alive, ordered by (time, pid) so
equal arrival times go to the lower pid; tickets of dead processes are returned for removal.
"""


def lock_turn(tickets: list[tuple[int, int]],
              live: set[int]) -> tuple[tuple[int, int] | None, list[tuple[int, int]]]:
    """Return (the oldest live ticket or None, the dead tickets in input order)."""
    return (min((t for t in tickets if t[1] in live), default=None),
            [t for t in tickets if t[1] not in live])
