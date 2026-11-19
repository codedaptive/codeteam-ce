"""The folder or file a git pathspec names, for the orchestrator's check of git rm, mv, restore,
checkout and stash push (D587: any write or removal that would change a file inside a code package
folder is refused; exclude pathspecs are not writes).

Magic is read in its long form (`:(top,glob)crates/*`) and its short form (`:/crates`, `:!x`,
`:^x`). `top` makes the base the repository top. A pattern with a glob character, plain or with
`glob` magic, is cut to its literal folder prefix, which holds everything it can match (git's
default matching lets `*` cross `/`, so `crates/*/main.rs` can name crates/cli/src/main.rs);
`literal` paths and paths with no glob character are taken as written.
Other magic words (icase, attr) do not change which folder is named. Reads only the filesystem: symlinks
and whether .git or .jj exists at or above cwd.
"""
import os

from git_top import git_top

GLOB_CHARS = "*?["
SHORT_MAGIC = {"/": "top", "!": "exclude", "^": "exclude"}


def _magic(arg: str) -> tuple[set[str], str]:
    """The magic words of arg and the path after them."""
    if not arg.startswith(":"):
        return set(), arg
    if arg.startswith(":("):
        words, _, path = arg[2:].partition(")")
        return {w.split(":", 1)[0].strip() for w in words.split(",")}, path
    i = 1
    while i < len(arg) and arg[i] in SHORT_MAGIC:
        i += 1
    path = arg[i + 1:] if arg[i:i + 1] == ":" else arg[i:]
    return {SHORT_MAGIC[c] for c in arg[1:i]}, path


def orc_pathspec(arg: str, cwd: str) -> str | None:
    """The absolute real path arg names when git runs in cwd, or None for exclude magic. For a
    pattern (not literal magic) it is the folder before the first glob character (the base when
    there is none)."""
    magic, path = _magic(arg)
    if "exclude" in magic:
        return None
    real_cwd = os.path.realpath(cwd)
    base = git_top(real_cwd) if "top" in magic else real_cwd
    cut = min((path.find(c) for c in GLOB_CHARS if c in path), default=len(path))
    if "literal" not in magic and cut < len(path):
        path = path[:cut].rpartition("/")[0]
    if not magic:
        path = os.path.expanduser(path)
    return os.path.realpath(os.path.join(base, path)) if path else base
