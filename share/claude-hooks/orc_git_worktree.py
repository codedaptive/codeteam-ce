"""The orc's git restore, checkout, clean, reset and stash, judged for code package folders (D587)."""
from orc_git_paths import orc_git_paths
from orc_git_stash import orc_git_stash
from orc_judge_from_file import orc_judge_from_file
from orc_judge_pathspec import orc_judge_pathspec
from orc_judge_top import orc_judge_top
from orc_rewrites_worktree import orc_rewrites_worktree


def orc_git_worktree(sub: str, rest: list[str], gcwd: str | None, where: list[str], manifest: str,
                     codeteam_home: str) -> str | None:
    """D587 for the orc's git restore, checkout, clean, reset and stash: the first refusal, else
    None. restore and checkout are judged by each pathspec they write, in order, then with
    --pathspec-from-file (not for restore writing only the index) by the repository top of each
    folder git acts on (where); clean and reset by that top when they rewrite the worktree; stash
    as orc_git_stash says. What passes unjudged: a pathspec holding `$`, exclude magic, a relative
    pathspec when the folder is unknown (a variable -C, gcwd None), and every top check when the
    folder is unknown."""
    if sub == "stash":
        return orc_git_stash(rest, gcwd, where, manifest, codeteam_home)
    if sub in ("restore", "checkout"):
        for a in orc_git_paths(sub, rest):
            why = orc_judge_pathspec(sub, a, gcwd, manifest, codeteam_home)
            if why:
                return why
        return orc_judge_from_file(sub, rest, gcwd, where, manifest, codeteam_home)
    if orc_rewrites_worktree(sub, rest):
        return orc_judge_top(sub, gcwd, where, manifest, codeteam_home)
    return None
