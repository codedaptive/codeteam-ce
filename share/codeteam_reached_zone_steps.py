"""Whether a reached zone runs its integration test group or its RITs at Stage 2 and the recheck.

Without a team RIT selector (mode b) every reached zone runs its integration group, narrowed to the
roots the change reaches. With one (mode a) the zones that hold a changed file run their integration test group and every other
reached zone (a direct caller, a contract consumer) runs only its RITs. The step builders stay in codeteam-land.
"""
from collections.abc import Callable


def reached_zone_steps(zones: list[str], changed: set[str], selector: str | None,
                       zit: Callable[[str], list], rits: Callable[[str], list]) -> list[tuple[str, str]]:
    """The steps for `zones` in their order: zit(zone) for each with no selector; with one, zit(zone) for a zone in
    `changed` and rits(zone) for the others."""
    return [step for zone in zones
            for step in (zit(zone) if selector is None or zone in changed else rits(zone))]
