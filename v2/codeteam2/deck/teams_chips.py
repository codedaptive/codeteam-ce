"""The chips of the deck's BUILDS teams row: a live runner's per-team job counts."""
from .busiest_teams import busiest_teams


def teams_chips(runner: dict) -> list[list[tuple[str, str]]]:
    """For a live runner with a non-empty "teams" object: dim "teams", then one chip per team in busiest_teams'
    order, the name bold and " <running> run <waiting> wait" dim. [] for any other runner, so there is no row."""
    teams = runner.get("teams")
    if runner.get("state") != "live" or not isinstance(teams, dict) or not teams:
        return []
    return [[("teams", "dim")]] + [[(str(name), "bold"), (f" {run:g} run {wait:g} wait", "dim")]
                                   for name, run, wait in busiest_teams(teams)]
