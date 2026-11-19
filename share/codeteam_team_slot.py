"""The build queue's team guarantee: which job a team with nothing running starts next.

"A build slot per team plus a shared pool. [...] A team with work waiting and nothing running is always started next,
ahead of the shared queue: one slot each, guaranteed. [...] A guarantee holds a slot only while the team has work
waiting; an idle team's slot stays in the pool, so nothing sits empty."

A team qualifies when no job of it is running (any class, run or slot kind) and it has a queued job the runner could
start now (`startable`: the holds a class head obeys). Its job is the one its own queue would start first: the first
class in start order with a startable job of that team, the oldest submitted there. Among qualifying teams the one
whose job was submitted first goes first; the runner asks again after each start, so every qualifying team starts in
the same decision.
"""
from collections.abc import Callable, Iterable

from codeteam_job_team import job_team


def team_slot(jobs: Iterable[dict], classes: Iterable[str],
              startable: Callable[[dict], bool]) -> dict | None:
    """The job the team guarantee starts next, or None when no team qualifies."""
    jobs = list(jobs)
    no_start = {job_team(j) for j in jobs if j.get("state") == "running"} | {None}
    rank = {cls: n for n, cls in enumerate(classes)}
    waiting = [j for j in jobs if j.get("state") == "queued" and j.get("class") in rank
               and job_team(j) not in no_start and startable(j)]
    first: dict = {}
    for j in sorted(waiting, key=lambda j: (rank[j["class"]], j["submitted"])):
        first.setdefault(job_team(j), j)
    return min(first.values(), key=lambda j: j["submitted"], default=None)
