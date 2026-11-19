"""The build queue's shared pool: which class head starts next once the team guarantee has passed.

Each class's head is offered in start order; the first the pool admits (`pool_admits`: under its guaranteed share, or
fitting the budget after the room reserved for classes under their share, and under its ceiling) starts.
"""
from collections import Counter

from codeteam_pool_admits import pool_admits


def class_pick(heads: dict[str, dict | None], running: list[dict], cfg) -> dict | None:
    """The shared pool's next job, or None: heads maps each class, in start order, to its next startable job (None
    when it has none), running is the running jobs, cfg has `shares` and `budget`."""
    used = sum(j.get("cost") or 0 for j in running)
    count = Counter(j.get("class") for j in running)
    return next((head for cls, head in heads.items()
                 if head is not None and pool_admits(cls, heads, count, used, cfg)), None)
