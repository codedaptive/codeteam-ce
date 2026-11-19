"""stale_copies: the superseded copies of build artifacts in one cargo deps folder.

cargo writes each build of a crate under a new hash (libfoo-<hash>.rlib, .rmeta, foo-<hash>.d) and never removes the
copy it replaced, so a clone reused build after build piles up every old copy. A copy is old only when both its
newest write and its newest read are a day back: another feature set or profile can still link a copy the latest
build did not write, and reading a file updates its atime on this volume, so a copy still in use shows a recent atime.
"""
import os
import re
from pathlib import Path

# <lib><name>-<16 hex>[.<ext>]: cargo's metadata hash. A name that does not match is never returned.
ENTRY = re.compile(r"^(lib)?(?P<name>.+)-(?P<hash>[0-9a-f]{16})(?P<ext>\..+)?$")
LIB_EXTS = (".rlib", ".rmeta", ".dylib", ".so", ".a")


def _copies(deps):
    """{hash: [(name, path, ext, lstat)]} for the matching entries of deps; {} when it cannot be listed. Keyed by the
    hash alone: a crate named libc writes liblibc-<hash>.rlib beside libc-<hash>.d. Only lstat: opening a file to look
    at it would update its atime and make every copy look in use."""
    try:
        entries = list(deps.iterdir())
    except OSError:
        return {}
    copies = {}
    for path in entries:
        match = ENTRY.match(path.name)
        if match is None:
            continue
        try:
            st = path.lstat()
        except OSError:
            continue
        copies.setdefault(match["hash"], []).append((match["name"], path, match["ext"], st))
    return copies


def _kind(entries):
    """"lib" when an entry is a library, else "exe" when one has no extension, else "other": a crate's binary and its
    library share a name but are different artifacts, and one never supersedes the other."""
    exts = [ext for _, _, ext, _ in entries]
    if any(ext in LIB_EXTS for ext in exts):
        return "lib"
    return "exe" if None in exts else "other"


def stale_copies(deps: Path, cutoff: float) -> list[list[Path]]:
    """Every entry of each copy in deps that is not its artifact's newest (by mtime) and whose newest mtime and newest
    atime are both at or before cutoff, one list per copy. [] when deps is missing, not a real folder or unlistable."""
    if not deps.is_dir() or deps.is_symlink():
        return []
    artifacts = {}
    for _, entries in sorted(_copies(deps).items()):
        # The artifact's name from its library or executable, not its .d file (libc-<hash>.d reads as "c").
        name = min((n for n, _, ext, _ in entries if ext != ".d"), default=entries[0][0])
        newest = (max(st.st_mtime for *_, st in entries), max(st.st_atime for *_, st in entries))
        artifacts.setdefault((name, _kind(entries)), []).append((newest, sorted(p for _, p, _, _ in entries)))
    stale = []
    for copies in artifacts.values():
        kept = max(copies, key=lambda c: c[0][0])
        stale += [c[1] for c in copies if c is not kept and max(c[0]) <= cutoff]
    return stale
