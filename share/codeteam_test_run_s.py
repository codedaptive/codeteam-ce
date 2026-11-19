"""test_run_s: R-26's measure of a landing's tests, the run time of its test steps alone (R-26, D564, D566).

Stage 2 rows name their step "step" and recheck rows "name"; only the steps is_test accepts count, and their run time
is the union of their run intervals (run_union), so steps side by side count once and serial steps add.
"""
from collections.abc import Callable

from codeteam_run_union import run_union


def test_run_s(rows: list[dict], is_test: Callable[[str], bool], run_seconds: Callable[[dict], float]) -> float:
    """run_union over the rows whose row.get("step") or row.get("name") satisfies is_test."""
    return run_union((row for row in rows if is_test(row.get("step") or row.get("name"))), run_seconds)
