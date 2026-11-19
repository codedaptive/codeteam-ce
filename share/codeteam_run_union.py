"""run_union: how long at least one of a landing's test steps was running (R-26, D564; codeteam-jj #4668).

R-26 limits a landing's tests to 15 minutes of run time. Steps side by side run at once, so their time counts once,
and serial steps add: the measure is the length of the union of the steps' run intervals. A step's run ends when its
output closed ("end") and began its run seconds before that, so a build-queue wait before the run is outside it, and
the run seconds it is given leave the build out (step_run_seconds, D585). A row without "end" has no place on the
clock and adds its run seconds.
"""
from collections.abc import Callable, Iterable


def run_union(rows: Iterable[dict], run_seconds: Callable[[dict], float]) -> float:
    """The length of the union of [end - run_seconds(row), end] over the rows with "end", plus run_seconds(row) for
    each row without one."""
    rows = list(rows)
    total = sum((run_seconds(row) for row in rows if "end" not in row), 0.0)
    reach = float("-inf")
    for start, end in sorted((row["end"] - run_seconds(row), row["end"]) for row in rows if "end" in row):
        total += max(0.0, end - max(start, reach))
        reach = max(reach, end)
    return total
