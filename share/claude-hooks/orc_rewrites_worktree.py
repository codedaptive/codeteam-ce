"""Whether the orc's git clean or reset rewrites the worktree as a whole (D587)."""


def orc_rewrites_worktree(sub: str, rest: list[str]) -> bool:
    """True when git clean (not a dry run) or reset --hard/--merge/--keep rewrites the worktree
    as a whole."""
    opts = rest[:rest.index("--")] if "--" in rest else rest
    if sub == "clean":
        return not any(a == "--dry-run" or (a[:1] == "-" and a[1:2] != "-" and "n" in a) for a in opts)
    return sub == "reset" and bool({"--hard", "--merge", "--keep"} & set(opts))
