"""The zone a Stage 5 recheck step belongs to.

The batch rule: "A failure in a batch is sent back to the zone that owns the failing code." A batched recheck attributes a
failing step to the batch row whose landing reached the step's zone (codeteam_batch_owner), so it needs that zone:
a compile step names it ("compile <zone> (<folder>)"), a test step's owner is the landing tool's step_owner, and any
other step (the type check, the repo gates) has none.
"""

from collections.abc import Callable


def step_zone(name: str, is_test_step: Callable[[str], bool], step_owner: Callable[[str], str]) -> str | None:
    """The zone a "compile <zone> (...)" step names; step_owner(name) for a test step; else None."""
    if name.startswith("compile ") and " (" in name:
        return name.split(" ", 1)[1].split(" (", 1)[0]
    return step_owner(name) if is_test_step(name) else None
