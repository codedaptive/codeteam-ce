"""prune_reused_trees: the watchdog's prune of superseded cargo output in the landing tool's long-lived clones.

A landing clone (land/itest, land/validate) is built in again and again and never cleaned, so its deps folders keep
every old copy of every crate (stale_copies) and its incremental folders keep the sessions of builds long gone. Both
are pruned at any free space once a day old (CUTOFF_S), and never in a clone with a build queued or running or one a
live Stage 5 or 6 run holds.
"""
import os
import shlex
import subprocess
import time
import tomllib
from pathlib import Path

from codeteam_newest_write import newest_write
from codeteam_stale_copies import stale_copies

# A day: a copy neither written nor read, or an incremental folder not written, that long belongs to no build in use.
CUTOFF_S = 86400
OUTPUTS = ("target", "cargo-target")


def _real_dirs(folder):
    """The real folders (not symlinks) in folder, sorted; none when it is not a real folder or cannot be listed."""
    if not folder.is_dir() or folder.is_symlink():
        return []
    try:
        return sorted(p for p in folder.iterdir() if p.is_dir() and not p.is_symlink())
    except OSError:
        return []


def _guards(m, q, queued_trees, runs_from, held_by):
    """(busy trees, held clones, the manifest names a hold may use) for the team of m, its builds read from q and,
    when its runners run another checkout's tool, from that checkout's queue too. None when that queue is missing:
    with it unread, a clone with a build queued there cannot be told from an idle one."""
    elsewhere = runs_from(m.stem)
    queues = [Path(q)] + ([elsewhere[0] / "run" / "queue"] if elsewhere else [])
    if not queues[-1].is_dir():
        return None
    names = {os.path.realpath(m), "*"} | ({os.path.realpath(elsewhere[1])} if elsewhere else set())
    busy = set().union(*(queued_trees(x) for x in queues))
    held = set().union(*(held_by(x.parent / "restart" / "stages") for x in queues))
    return busy, held, names


def _victims(tree, cutoff):
    """(old copies, old incremental folders) in each profile of tree's cargo output folders."""
    copies, folders = [], []
    for profile in (p for out in OUTPUTS if not (tree / out).is_symlink() for p in _real_dirs(tree / out)):
        copies += stale_copies(profile / "deps", cutoff)
        folders += [f for f in _real_dirs(profile / "incremental") if newest_write(f) <= cutoff]
    return copies, folders


def _size(path):
    """lstat bytes of path, or of every file under it when it is a real folder."""
    if not path.is_dir() or path.is_symlink():
        return path.lstat().st_size
    return sum((Path(d) / f).lstat().st_size for d, _, files in os.walk(path) for f in files)


def _take(path, trash, label, dry_run):
    """(path's bytes, whether it went to trash) once it is removed: a file unlinked, a folder moved to trash as label.
    A dry run removes nothing and says what would go. None when it fails."""
    try:
        size, folder = _size(path), path.is_dir() and not path.is_symlink()
        if dry_run:
            return size, False
        if folder:
            trash.mkdir(exist_ok=True)
            path.rename(trash / label)
        else:
            path.unlink()
        return size, folder
    except OSError:
        return None


def _prune_tree(tree, trash, now, dry_run):
    """(files, copies, incremental folders, bytes, whether trash got anything) removed from tree."""
    copies, folders = _victims(tree, now - CUTOFF_S)
    label = f"{time.strftime('%Y%m%d-%H%M%S', time.localtime(now))}-{tree.name}"
    files = n_copies = n_folders = freed = n = 0
    trashed = False
    for entries in copies:
        taken = 0
        for path in entries:
            n += 1
            got = _take(path, trash, f"{label}-{n}-{path.name}", dry_run)
            if got is not None:
                taken, freed, trashed = taken + 1, freed + got[0], trashed or got[1]
        files, n_copies = files + taken, n_copies + (taken > 0)
    for folder in folders:
        n += 1
        got = _take(folder, trash, f"{label}-{n}-incremental-{folder.name}", dry_run)
        if got is not None:
            n_folders, freed, trashed = n_folders + 1, freed + got[0], trashed or got[1]
    return files, n_copies, n_folders, freed, trashed


def _idle(tree, kind, guards):
    """Whether the clone tree may be pruned: a real folder with no build queued or running and no live hold on it."""
    busy, held, names = guards
    return (os.path.realpath(tree) not in busy and not any((name, kind) in held for name in names)
            and tree.is_dir() and not tree.is_symlink())


def _prune_team(m, q, queued_trees, runs_from, clones, held_by, now, dry_run):
    """(one line per landing clone of m's team pruned, the team's root when its .trash got a folder, else None); no
    lines when the manifest cannot be read or a queue it needs is missing (_guards)."""
    try:
        cfg = tomllib.loads(m.read_text())
    except (OSError, ValueError):
        return [], None
    root = Path(os.path.expanduser(cfg.get("worktree_root") or f"~/codeteam-work/team-{m.stem}"))
    guards = _guards(m, q, queued_trees, runs_from, held_by)
    if guards is None:
        return [], None
    lines, trashed_root = [], None
    for kind, tree in sorted(clones(cfg, root).items()):
        if not _idle(tree, kind, guards):
            continue
        files, copies, folders, freed, trashed = _prune_tree(tree, root / ".trash", now, dry_run)
        trashed_root = root if trashed else trashed_root
        if not files + folders:
            continue
        verb, tail = ("would prune", "bytes") if dry_run else ("pruned", "bytes freed")
        line = f"{verb} {tree}: {files} files in {copies} old copies, {folders} incremental folders, {freed} {tail}"
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))} {line}", flush=True)
        lines.append(line)
    return lines, trashed_root


def prune_reused_trees(manifests, q, queued_trees, runs_from, clones, held_by, now=None, dry_run=False,
                       popen=subprocess.Popen) -> list[str]:
    """For each team, prunes old copies and incremental folders (_victims) in each landing clone (clones) that has no
    build queued or running (queued_trees) and that no live Stage 5 or 6 run holds (held_by), then empties each
    root's .trash that received a folder in the background. Prints and returns one line per clone pruned; dry_run
    removes, moves and starts nothing and says what it would prune. When q is not a folder it removes nothing and
    reads no manifest."""
    if not Path(q).is_dir():
        return []
    now = time.time() if now is None else now
    results = [_prune_team(m, q, queued_trees, runs_from, clones, held_by, now, dry_run) for m in manifests]
    for root in sorted({root for _, root in results if root is not None}):
        popen(["sh", "-c", f"rm -rf {shlex.quote(str(root / '.trash'))}/*"], stdout=subprocess.DEVNULL,
              stderr=subprocess.DEVNULL, start_new_session=True)
    return [line for lines, _ in results for line in lines]
