"""A work order tree's commits that landing does not hold (Orc-Codegraph #4653, D559)."""
import subprocess


def unlanded_commits(tree: str | None, landing: str) -> list[str]:
    """The non-merge commits of the tree's HEAD not on landing, newest first; none when no tree is named or git cannot
    read it (the tree is gone)."""
    if not tree:
        return []
    found = subprocess.run(["git", "-C", tree, "rev-list", "--no-merges", "HEAD", f"^{landing}"],
                           capture_output=True, text=True)
    return found.stdout.split() if found.returncode == 0 else []
