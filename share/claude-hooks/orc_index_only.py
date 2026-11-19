"""Whether the orc's git command writes only the index, not the worktree (D587)."""
from orc_git_value_options import ORC_GIT_VALUE_OPTIONS


def orc_index_only(sub: str, rest: list[str]) -> bool:
    """True for git restore with --staged/-S and without --worktree/-W, which writes only the
    index. Only the words before the first `--` are options (after it every word is a pathspec),
    and the word right after an ORC_GIT_VALUE_OPTIONS option is that option's value, not an option."""
    cut = rest.index("--") if "--" in rest else len(rest)
    options = {a for j, a in enumerate(rest[:cut]) if not (j and rest[j - 1] in ORC_GIT_VALUE_OPTIONS)}
    return sub == "restore" and bool({"--staged", "-S"} & options) and not {"--worktree", "-W"} & options
