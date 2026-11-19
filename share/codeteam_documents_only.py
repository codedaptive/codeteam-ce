"""The scope of a zone entry that holds documents alone (D589).

A zone entry with no package manifest has the whole tree as its scope, so every change reaches its zone, unless the
entry holds documents alone (the team's docs_only_suffixes): an owned document file, or a folder whose every file is
one, an empty folder included. Such an entry is its own scope. codeteam-land's reach calls this from its nested scope;
the caller passes Path.is_file and os.walk, so this stays a function of its arguments.
"""
from collections.abc import Callable, Iterable
from pathlib import PurePosixPath


def documents_only(entry: str, path, suffixes: tuple[str, ...], is_file: Callable[[object], bool],
                   walk: Callable[[object], Iterable[tuple[str, list[str], list[str]]]]) -> list[str]:
    """The scope of zone entry `entry`, found at `path`, with no package manifest: [entry] when it is a file whose
    name ends with one of `suffixes`, or a folder whose every file (outside .git) does, an empty folder included;
    else ["."], the whole tree. The tree root ("." or "") is never inspected."""
    if entry in (".", ""):
        return ["."]
    if is_file(path):
        return [entry] if PurePosixPath(entry).name.endswith(suffixes) else ["."]
    for _, subdirs, names in walk(path):
        subdirs[:] = [x for x in subdirs if x != ".git"]
        if not all(n.endswith(suffixes) for n in names if n != ".git"):
            return ["."]
    return [entry]
