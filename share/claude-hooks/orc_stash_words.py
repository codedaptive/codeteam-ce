"""The action and pathspecs of the orc's git stash (D587)."""

# git stash's options whose next word is a value, not its action or a pathspec.
STASH_VALUE_OPTIONS = {"-m", "--message", "--pathspec-from-file"}


def orc_stash_words(rest: list[str]) -> tuple[str, list[str]]:
    """(action, pathspecs) of git stash. The action is the first word before any `--` that is not
    an option or the value of -m/--message/--pathspec-from-file, "" when there is none. The
    pathspecs: for push, its other such words and every word after `--`; with no action, the words
    after `--`; none for any other action (save's words are its message)."""
    cut = rest.index("--") if "--" in rest else len(rest)
    words = [a for j, a in enumerate(rest[:cut]) if not a.startswith("-")
             and not (j and rest[j - 1] in STASH_VALUE_OPTIONS)]
    action = words[0] if words else ""
    if action == "push":
        return action, words[1:] + rest[cut + 1:]
    return action, rest[cut + 1:] if action == "" else []
