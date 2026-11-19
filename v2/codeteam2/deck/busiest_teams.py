"""The order the deck lists teams in by their build queue counts: busiest first."""
import math


def _count(entry, key):
    # A count that is not a finite number (a bool included) counts as 0, as render's _num(x) or 0 reads it.
    value = entry.get(key) if isinstance(entry, dict) else None
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    return value if ok else 0


def busiest_teams(teams: dict) -> list[tuple[str, int, int]]:
    """(name, running, waiting) for each team of a runner's "teams" ({name: {"running", "waiting"}}): more running
    first, then more waiting, then the name."""
    return sorted(((name, _count(c, "running"), _count(c, "waiting")) for name, c in teams.items()),
                  key=lambda t: (-t[1], -t[2], t[0]))
