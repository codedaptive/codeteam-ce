"""The orc's git command with --pathspec-from-file, judged by its repository top (D587)."""
from orc_from_file import orc_from_file
from orc_index_only import orc_index_only
from orc_judge_top import orc_judge_top


def orc_judge_from_file(sub: str, rest: list[str], gcwd: str | None, where: list[str],
                        manifest: str, codeteam_home: str) -> str | None:
    """D587: the repository top's refusal when sub takes --pathspec-from-file and writes the
    worktree, else None."""
    if orc_from_file(rest) and not orc_index_only(sub, rest):
        return orc_judge_top(sub, gcwd, where, manifest, codeteam_home)
    return None
