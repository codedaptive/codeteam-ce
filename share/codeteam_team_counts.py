"""Each team's running and waiting build-queue jobs, for the runner's heartbeat.

"Show each team's running and waiting count in queue-runner.json and the deck." Keyed by the team without its "team-"
prefix ("acme", "widgets"); jobs with no team count under "-". Waiting is every queued job, held or not. A team with
neither a running nor a queued job is left out.
"""
from collections.abc import Iterable

from codeteam_job_team import job_team

FIELD = {"running": "running", "queued": "waiting"}  # job state -> the count it adds to


def team_counts(jobs: Iterable[dict]) -> dict:
    """{team: {"running": n, "waiting": n}} over the running and queued jobs."""
    counts: dict = {}
    for j in jobs:
        field = FIELD.get(j.get("state"))
        if field is None:
            continue
        team = job_team(j)
        name = team.removeprefix("team-") if team else "-"
        counts.setdefault(name, {"running": 0, "waiting": 0})[field] += 1
    return counts
