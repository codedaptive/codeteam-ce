"""The team a build-queue job belongs to.

"The team is the job's team field, or else its worktree's team folder." The worktree rule is the one zone-tool's
new_job already uses to fill the field: the first part of the path that starts with "team-". A job with neither has
no team; it is in the shared pool only.
"""
from pathlib import Path


def job_team(job: dict) -> str | None:
    """job["team"] when it is a non-empty string, else the worktree's first "team-" folder, else None."""
    team = job.get("team")
    if isinstance(team, str) and team:
        return team
    return next((part for part in Path(job.get("worktree") or "").parts if part.startswith("team-")), None)
