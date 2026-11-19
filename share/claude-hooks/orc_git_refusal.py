"""The orchestrator's git command, judged for code package folders (D587)."""
from orc_git_worktree import orc_git_worktree
from orc_judge_from_file import orc_judge_from_file
from orc_judge_pathspec import orc_judge_pathspec

# The git subcommands that rewrite worktree files without staging them.
ORC_WORKTREE_GIT = ("restore", "checkout", "clean", "reset", "stash")


def orc_git_refusal(sub: str, rest: list[str], gcwd: str | None, where: list[str], manifest: str,
                    codeteam_home: str) -> str | None:
    """D587 for the orchestrator's git sub with the words after it (rest): the first refusal,
    else None. restore, checkout, clean, reset and stash are judged by orc_git_worktree. rm and
    mv are judged first by the repository top when they read --pathspec-from-file, then by each
    pathspec in order (the words after `--`, else the words that are not options), -A skipped.
    add is not judged, as in codeteam-jj: staging writes no file, and the edit-time and shell-write
    checks already guard the files. Every other subcommand (merge, commit, push, ...) is not
    judged either."""
    if sub in ORC_WORKTREE_GIT:
        return orc_git_worktree(sub, rest, gcwd, where, manifest, codeteam_home)
    if sub not in ("rm", "mv"):
        return None
    why = orc_judge_from_file(sub, rest, gcwd, where, manifest, codeteam_home)
    if why:
        return why
    cands = rest[rest.index("--") + 1:] if "--" in rest else [a for a in rest if a and not a.startswith("-")]
    judged = (orc_judge_pathspec(sub, a, gcwd, manifest, codeteam_home) for a in cands if a != "-A")
    return next(filter(None, judged), None)
