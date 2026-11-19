"""Drop the build output of a lane the loop ended for being idle (D598).

An idle lane's standing tree keeps its build folders (often gigabytes) until something cleans them; the loop
starts a detached zone-clean there once the lane it ended is seen gone. A v5 zone-folder lane has no standing
tree, a non-git folder is not a tree zone-clean knows, and a tree with a running build-queue job in it (or in a
request tree nested inside it) is left alone. The loop must never stop for this, so every error is logged and swallowed.
"""
import os
from pathlib import Path

from .idle_clean_trees import idle_clean_trees
from .start_zone_clean import start_zone_clean
from .team import CT_HOME, v1


def _running_worktrees() -> list[str]:
    from .deck.collect import read_job      # here, not at the top: deck.collect imports scheduler, which imports us
    queue = Path(os.environ.get("CODETEAM_QUEUE_DIR") or CT_HOME / "run" / "queue")
    if not queue.is_dir():
        return []
    jobs = (read_job(p) for p in sorted(queue.glob("*.json")) if not p.name.startswith("."))
    return [j["worktree"] for j in jobs if j and j.get("state") == "running" and j.get("worktree")]


def clean_idle_lane(team, session, log) -> None:
    """Start zone-clean in the idle-ended lane's standing tree when it is safe; log what was done."""
    try:
        if session.kind != "lane":
            return
        rec = team.team_json()["lanes"][session.key]
        trees = [] if v1._zone_folder_lane(team.t, rec) else [v1.lane_wt(team.t, session.key, rec)]
        candidates = [(tree, (tree / ".git").exists()) for tree in trees]
        for tree in idle_clean_trees(session.kind, candidates, _running_worktrees()):
            started = start_zone_clean(tree, CT_HOME)
            log(f"idle clean {session.display}: zone-clean "
                f"{'handed to a detached sh' if started else 'not started'} in {tree}")
    except Exception as e:          # an economy: it never stops the loop
        log(f"idle clean {session.display}: {type(e).__name__}: {e}")
