"""newest_write: the newest write time in a folder's top two levels, read by the watchdog's stale-target sweep and its
prune of reused landing clones."""
import itertools

# Entries listed per folder (a deps folder holds thousands). Only the top two levels are read, LIST_CAP entries per
# folder: a write deeper down is seen only when it changes an entry at those levels (adding or removing a file
# updates its folder's mtime).
LIST_CAP = 200


def _listing(folder):
    """Up to LIST_CAP entries of folder; none when it is not a real folder or cannot be listed."""
    if not folder.is_dir() or folder.is_symlink():
        return []
    try:
        return list(itertools.islice(folder.iterdir(), LIST_CAP))
    except OSError:
        return []


def newest_write(t) -> float:
    """The newest lstat mtime of t, its entries and their entries (LIST_CAP listed per folder): a build running
    outside the queue writes there. float("inf") when none can be stat'ed (t vanished): an unknown write time counts
    as now, the safe side for both callers, which then keep t."""
    entries = _listing(t)
    times = []
    for p in [t, *entries, *(e for d in entries for e in _listing(d))]:
        try:
            times.append(p.lstat().st_mtime)
        except OSError:
            pass
    return max(times, default=float("inf"))
