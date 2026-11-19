"""When a work order's tree last moved, judged by its own commits."""
import subprocess


def own_work_time(tree, base) -> float | None:
    """The time of the last commit in tree when it has a commit of its own past base; None when it has none, base is
    empty, or git cannot answer."""
    def git(*a):
        return subprocess.run(["git", "-C", str(tree), *a], capture_output=True, text=True, timeout=20).stdout
    # Cheap on purpose (this runs inside the loop's tick, over every open tree): two small git calls, never a walk
    # of the tree. Work = a commit of its own; the time of its last commit is when it last moved (the index file's
    # time is no measure: any `git status` rewrites it).
    try:
        own = git("rev-list", "--count", f"{base}..HEAD").strip() if base else "0"
        if own in ("", "0"):
            return None                     # no commit of its own: held on purpose, or left by a cancelled start
        return float(git("log", "-1", "--format=%ct").strip() or 0)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
