"""The fields the deck takes from a live build queue runner's queue-runner.json."""
from collections.abc import Callable

from .runner_teams import runner_teams


def live_fields(data: dict, numbers: tuple, holds: tuple, finite: Callable[[object], bool]) -> dict:
    """Each key of numbers with its value when finite says so, each key of holds with its value when a bool (any
    other value None) and, when data has a "teams" object, "teams" with its valid per-team job counts
    (runner_teams); no "teams" key otherwise."""
    teams = runner_teams(data.get("teams"))
    return {**{k: data[k] if finite(data.get(k)) else None for k in numbers},
            **{k: data[k] if isinstance(data.get(k), bool) else None for k in holds},
            **({} if teams is None else {"teams": teams})}
