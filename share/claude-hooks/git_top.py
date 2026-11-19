"""The repository top a git command run in a folder works against."""
from pathlib import Path


def git_top(cwd: str) -> str:
    """The nearest folder at or above cwd holding .git or .jj, else cwd; the repository top
    (orc_pathspec.py uses it for `:/` pathspecs; orc_judge_top.py for git clean, reset, stash and
    --pathspec-from-file)."""
    p = Path(cwd)
    return str(next((a for a in [p, *p.parents] if (a / ".git").exists() or (a / ".jj").exists()), p))
