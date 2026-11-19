"""Whether the build queue's shared pool starts a class's next job now (after the team guarantee).

A class under its guaranteed share always starts its next job, even over the budget. Past its share it borrows: its
next job starts when its cost fits the budget beside the running jobs (team-guarantee starts count like any other)
plus the room every other class under its guaranteed share reserves for its own waiting next job, and the
class is under its ceiling (0 means none).
"""
from collections import Counter


def pool_admits(cls: str, heads: dict[str, dict | None], count: Counter, used: float, cfg) -> bool:
    """True when class cls's head (heads[cls], with a cost) may start: count is running jobs per class, used the sum
    of their costs, cfg has `shares` ({class: (guaranteed, ceiling)}) and `budget`."""
    guaranteed, ceiling = cfg.shares[cls]
    if count[cls] < guaranteed:
        return True
    reserved = sum(h["cost"] for o, h in heads.items() if o != cls and h and count[o] < cfg.shares[o][0])
    return used + heads[cls]["cost"] + reserved <= cfg.budget and (ceiling == 0 or count[cls] < ceiling)
