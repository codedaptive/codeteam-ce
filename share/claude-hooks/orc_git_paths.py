"""The pathspecs the orc's git restore or checkout writes (D587)."""
from orc_git_value_options import ORC_GIT_VALUE_OPTIONS
from orc_index_only import orc_index_only


def orc_git_paths(sub: str, rest: list[str]) -> list[str]:
    """The pathspecs git restore or checkout writes: every word after `--`, and before it (or with
    no `--`) the words that are not options or option values. Checkout's words before a `--` are
    revisions, not pathspecs; without `--` each word is judged as a path, so a branch name passes
    as a path holding no package. restore --staged without --worktree writes only the index: none."""
    if orc_index_only(sub, rest):
        return []
    cut = rest.index("--") if "--" in rest else len(rest)
    after = rest[cut + 1:]
    if sub == "checkout" and cut < len(rest):
        return after
    return [a for j, a in enumerate(rest[:cut]) if not a.startswith("-")
            and not (j and rest[j - 1] in ORC_GIT_VALUE_OPTIONS)] + after
