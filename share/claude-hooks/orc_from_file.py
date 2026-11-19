"""Whether the orc's git command reads its pathspecs from a file (D587)."""


def orc_from_file(rest: list[str]) -> bool:
    """True when --pathspec-from-file comes before any `--`: the pathspecs are in a file the guard
    does not read."""
    opts = rest[:rest.index("--")] if "--" in rest else rest
    return any(a == "--pathspec-from-file" or a.startswith("--pathspec-from-file=") for a in opts)
