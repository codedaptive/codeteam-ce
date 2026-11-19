"""clean_settled_env: empties the env of every settled job file in the build queue, at the runner's start (D560).

A settled job file can still hold an env (one written by a client or runner without `settled_env`); the runner calls
this once after it takes its lock, so a restart cleans the folder. Queued and running jobs keep their env: the runner still hands it to a child.
"""
from __future__ import annotations

from codeteam_settled_env import settled_env


def clean_settled_env(queue) -> int:
    """For each job in `queue.all()` whose env settled_env would empty, `queue.update` it to env `{}` while it is
    still in the state it was read in. The number of jobs written; one whose state changed in between is not."""
    written = 0
    for job in queue.all():
        if settled_env(job).get("env") != job.get("env"):
            written += queue.update(job["ticket"], {"env": {}}, expect=job["state"]) is not None
    return written
