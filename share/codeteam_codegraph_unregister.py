"""Unregister a worktree from CodeGraph before the tree is removed (D597).

CodeGraph's server keeps a registered tree's index open; unregistering lets it let go of that index, so a removed
tree leaves nothing held. It is best effort: a missing CLI, a failing call or one that hangs never stops the caller.
"""
import subprocess

TIMEOUT = 60    # seconds; the call only drops a registration, so a hang is the server's problem, not the caller's


def codegraph_unregister(cg: str, path) -> None:
    """Run `<cg> project remove <path>`, its output captured; an OSError, a nonzero exit or a timeout is ignored."""
    try:
        subprocess.run([cg, "project", "remove", str(path)], capture_output=True, timeout=TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired):
        pass
