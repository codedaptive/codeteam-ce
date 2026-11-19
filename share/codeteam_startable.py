"""Whether the build queue may start a queued job in this decision: the holds a class head and the team guarantee both
obey.

A job starts only when the swap guard does not hold its class, it has a cost (a job submitted since this decision
priced the queue waits for the next one), its worktree is not still being warmed, and no running job holds its
worktree and port. One build at a time per worktree and port (2026-11-04: WidgetStoreKit submitted 16 Swift groups at
once, they started together in one worktree, and xcodebuild failed on its locked build database): a queued job waits
while a job for the same worktree and port runs; jobs in other worktrees or the other port go ahead.
"""
from collections.abc import Callable


def startable(job: dict, busy: set[tuple], hold: Callable[[str], str | None],
              warm: Callable[[object], bool], port: Callable[[dict], str | None]) -> bool:
    """True when job may start: busy is the (worktree, port) of every running job with a port, hold the swap guard's
    reason for holding a class (None when it does not), warm whether a warm lock is held, port a job's port or None."""
    return (hold(job["class"]) is None and job.get("cost") is not None and not warm(job.get("warm_lock"))
            and (not port(job) or (job.get("worktree"), port(job)) not in busy))
