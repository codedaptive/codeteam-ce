"""A range's own commits, a merge's own changes included.

A merge counts by what `git show --remerge-diff` shows: the difference between git's automatic merge of its parents
and the merge as committed. A clean merge shows nothing, so it adds nothing; a merge resolved by hand shows the
resolution, so it counts like any other own commit. `rev-list --no-merges` would drop the resolution with the merge.
"""
import subprocess


def own_commits(repo: str, revs: list[str]) -> list[str]:
    """The commits `git rev-list <revs>` lists, in its order, less each merge whose remerge diff names no file.
    Raises subprocess.CalledProcessError when git cannot read the range."""
    listed = [line.split() for line in _git(repo, "rev-list", "--parents", *revs).splitlines()]
    return [commit for commit, *parents in listed if len(parents) < 2 or _resolved(repo, commit)]


def _resolved(repo: str, merge: str) -> bool:
    return bool(_git(repo, "show", "--remerge-diff", "--no-renames", "--format=", "--name-only", merge).strip())


def _git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout
