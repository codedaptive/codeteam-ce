"""A work order tree's commits that landing does not hold (Orc-Codegraph #4653, D559)."""
import subprocess

from codeteam_own_commits import own_commits


def unlanded_commits(tree: str | None, landing: str) -> list[str]:
    """The own commits of the tree's HEAD not on landing, newest first: its non-merge commits and each merge resolved
    by hand; none when no tree is named or git cannot read it (the tree is gone)."""
    if not tree:
        return []
    try:
        return own_commits(tree, ["HEAD", f"^{landing}"])
    except subprocess.CalledProcessError:
        return []
