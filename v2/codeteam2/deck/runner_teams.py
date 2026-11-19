"""The per-team job counts of queue-runner.json's "teams" object, as the deck may show them."""


def _count(value):
    # A bool is an int to isinstance; true is not a job count.
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def runner_teams(value) -> dict | None:
    """The valid entries of the runner's "teams" value: each team name (a str; "-" for jobs with no team) with its
    "running" and "waiting" job counts, both ints of 0 or more. An entry of any other shape is dropped. None when
    the value is not an object, so the caller adds no "teams" at all."""
    if not isinstance(value, dict):
        return None
    return {name: {"running": counts["running"], "waiting": counts["waiting"]} for name, counts in value.items()
            if isinstance(name, str) and isinstance(counts, dict)
            and _count(counts.get("running")) and _count(counts.get("waiting"))}
