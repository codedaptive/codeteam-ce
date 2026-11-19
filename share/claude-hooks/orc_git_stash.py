"""The orc's git stash, judged by its pathspecs or its repository top (D587)."""
from orc_from_file import orc_from_file
from orc_judge_pathspec import orc_judge_pathspec
from orc_judge_top import orc_judge_top
from orc_stash_words import orc_stash_words

# The stash actions that write the worktree from a stash; the push forms are "", push and save.
STASH_APPLIES = ("pop", "apply", "branch")


def orc_git_stash(rest: list[str], gcwd: str | None, where: list[str], manifest: str,
                  codeteam_home: str) -> str | None:
    """D587 for the orc's git stash: the first refusal, else None. pop, apply and branch are judged
    by the repository top. The push forms (no action, push, save) judge each pathspec in order, and
    the repository top when there is none or they come from --pathspec-from-file, so a bare
    `git stash` in a tree holding a package is refused. list, show, drop, clear, create and store
    leave the worktree alone: not judged."""
    action, paths = orc_stash_words(rest)
    if action not in ("", "push", "save", *STASH_APPLIES):
        return None
    for a in paths:
        why = orc_judge_pathspec("stash", a, gcwd, manifest, codeteam_home)
        if why:
            return why
    if action in STASH_APPLIES or not paths or orc_from_file(rest):
        return orc_judge_top("stash", gcwd, where, manifest, codeteam_home)
    return None
