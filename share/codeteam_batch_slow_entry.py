"""Which entry of a Stage 2 batch the slow-tests report names as its source.

queue-run tests a batch of ready entries in one integration run, so its slow-tests flag covers the whole batch. The
follow-up goes to the entry that brought the slowest step into the run: among the entries whose zones hold the slowest
step's zone, the one reaching the most zones (it pulled in the widest set of zones), the earlier in queue-run's order on
a tie. With no flag, no steps, or no entry reaching that zone, the first entry is the source.
"""

from collections.abc import Callable


def batch_slow_entry(flag: dict | None, entries: list[dict], step_owner: Callable[[str], str]) -> dict:
    """The entry of entries the slow-tests report names: step_owner resolves the zone of flag["steps"][0] (slowest
    first); the widest entry whose "zones" holds it, earlier on a tie; else, or without steps, entries[0]."""
    if not flag or not flag.get("steps"):
        return entries[0]
    zone = step_owner(flag["steps"][0]["step"])
    reaching = [entry for entry in entries if zone in entry.get("zones", [])]
    return max(reaching, key=lambda entry: len(entry["zones"]), default=entries[0])
