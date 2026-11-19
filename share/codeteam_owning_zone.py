"""The zone that owns a path (D491, creator #4379 Q-stage2-reach2).

A changed test file reaches only its owner, and in mode (a) a changed file's owner runs its ZIT group. The owner is
the zone with the most specific owned entry that holds the path: a lane owning `tests/unit/land-*.py` owns that file
over a lane owning `tests` or the whole repo. The caller passes its own matcher, which matches globs (codeteam-land's
in_scope); a prefix-only match misses glob owners.
"""
from collections.abc import Callable


def owning_zone(zones: dict[str, list[str]], path: str, in_scope: Callable[[str, str], bool]) -> str | None:
    """The zone whose owned entry d with in_scope(path, d) is longest ("." and "" count 0); on a tie the first zone
    in `zones`' order; None when no entry holds the path."""
    owner, longest = None, -1
    for zone, entries in zones.items():
        for entry in entries:
            length = 0 if entry in (".", "") else len(entry)
            if length > longest and in_scope(path, entry):
                owner, longest = zone, length
    return owner
