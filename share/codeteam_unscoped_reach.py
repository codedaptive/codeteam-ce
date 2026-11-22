"""What a changed file in no zone's scope reaches.

Reach (bin/codeteam-land) sends a changed file that no zone holds to every zone, unless this module knows better. A
document reaches nothing of its own: a landing of documents alone runs no tests, so a document beside code must not
widen the run. A Cargo.lock reaches the zones holding the workspace crates it changes between the landing's base and
HEAD; widgets's one-line lock change otherwise ran 55 steps over 7 zones. Both sides of the lock are read with
`git show`, since the build may touch the working copy.
"""
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

from codeteam_cargo_folders import cargo_package_folders
from codeteam_lock_reach import lock_changed_folders


def unscoped_reach(tree, path: str, base: str | None, docs: tuple[str, ...],
                   owners: Callable[[str], set[str]]) -> set[str] | None:
    """The zones `path`, a changed file in no zone's scope, reaches: set() for a document (a `docs` suffix) and for any
    other file that is not a Cargo.lock (2026-11-21: an integration run tests the changed kit and the kits
    that touch it, never every kit; a root file that a kit does depend on says so in [land.contracts], which the
    caller adds). For a Cargo.lock, the owners of the workspace folders whose packages it changes between `base` and
    HEAD. None, for the caller to answer every zone, only when a lock's reach is not known: no base, the lock missing
    at either side, no workspace manifest beside it, a lock that does not parse, or a reached folder no zone holds."""
    if path.endswith(docs):
        return set()
    if os.path.basename(path) != "Cargo.lock":
        return set()
    if base is None:
        return None
    sides = [subprocess.run(["git", "show", f"{rev}:{path}"], cwd=tree, capture_output=True, text=True)
             for rev in (base, "HEAD")]
    if any(side.returncode for side in sides):
        return None
    where = os.path.dirname(path)
    folders = cargo_package_folders(Path(tree) / where)
    changed = None if folders is None else lock_changed_folders(sides[0].stdout, sides[1].stdout, folders)
    if changed is None:
        return None
    zones = [owners(f"{where}/{c}" if where else c) for c in changed]
    return None if not all(zones) else set().union(*zones)
