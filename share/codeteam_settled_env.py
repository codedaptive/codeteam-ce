"""settled_env: a build-queue job as its file should hold it, with no environment once the job has settled (D560).

A run job carries the submitter's whole environment (`env`) while it is queued or running, because the runner hands
it to the child it starts. Nothing reads a settled job's env, so a settled job's file keeps none. The key stays, as
`{}`: the runner's `well_formed` requires `env` on run jobs in every state, and a job file without it is skipped.
"""
from __future__ import annotations

# A cancel settles a job as state "broken" with reason "cancelled"; there is no cancelled state.
_SETTLED = ("done", "broken")


def settled_env(job: dict) -> dict:
    """A copy of a settled job that has an `env` key, with env `{}` (a copy even when env is already empty, so the
    caller's dict is never changed); any other job, itself."""
    if job.get("state") in _SETTLED and "env" in job:
        return {**job, "env": {}}
    return job
