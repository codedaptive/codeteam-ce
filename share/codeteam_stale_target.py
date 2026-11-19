"""sweep_stale_targets: the watchdog's removal of dead <tree>/target folders in teams that build into cargo-target.

A team with CODETEAM_CARGO_TARGET=1 builds each work order tree into <tree>/cargo-target through codeteam's cargo
wrapper, so nothing should build into <tree>/target. One found beside cargo-target is cold output from a build that
skipped the wrapper (landing builds did), and it is removed at any free space, not only below the disk floor.
"""
import os
import shlex
import subprocess
import time
import tomllib
from pathlib import Path

from codeteam_newest_write import newest_write
from codeteam_order_trees import order_trees

def _opted_in_root(m):
    """The worktree root of the team whose manifest is m when its [env] sets CODETEAM_CARGO_TARGET to 1, else None
    (also when the manifest cannot be read)."""
    try:
        cfg = tomllib.loads(m.read_text())
    except (OSError, ValueError):
        return None
    if str((cfg.get("env") or {}).get("CODETEAM_CARGO_TARGET")) != "1":
        return None
    return Path(os.path.expanduser(cfg.get("worktree_root") or f"~/codeteam-work/team-{m.stem}"))


def _stale(tree, busy, since):
    """tree/target when it is a real folder beside a cargo-target folder, the tree has no queued or running build,
    and nothing in its top two levels was written after since; else None. Activity elsewhere in the tree (a lead
    editing) does not keep it: the folder is dead output either way."""
    t = tree / "target"
    if not t.is_dir() or t.is_symlink() or not (tree / "cargo-target").is_dir():
        return None
    if os.path.realpath(tree) in busy or newest_write(t) > since:
        return None
    return t


def sweep_stale_targets(manifests, q, queued_trees, runs_from, have_gb, now=None, quiet_s=1800,
                        popen=subprocess.Popen) -> list[str]:
    """For each opted-in team, moves every stale tree/target (_stale) among its work order trees (order_trees) to the
    root's .trash, then empties each .trash that received one in the background. A team whose runners run another
    checkout's tool (runs_from) has its builds read from that checkout's queue too. Prints and returns one line per
    folder removed. When q is not a folder it removes nothing and reads no manifest: with no queue to read it cannot
    tell a tree with a build queued or running from an idle one."""
    if not Path(q).is_dir():
        return []
    now = time.time() if now is None else now
    stamp = time.localtime(now)
    done, emptied = [], set()
    for m in manifests:
        root = _opted_in_root(m)
        if root is None:
            continue
        elsewhere = runs_from(m.stem)
        busy = queued_trees(q) | (queued_trees(elsewhere[0] / "run" / "queue") if elsewhere else set())
        for tree in sorted(order_trees(root)):
            t = _stale(tree, busy, now - quiet_s)
            if t is None:
                continue
            try:
                (root / ".trash").mkdir(exist_ok=True)
                t.rename(root / ".trash" / f"{time.strftime('%Y%m%d-%H%M%S', stamp)}-{tree.name}-target")
            except OSError:
                continue
            emptied.add(root)
            line = f"removed {t} (beside cargo-target; no build queued or running)"
            print(f"{time.strftime('%Y-%m-%d %H:%M:%S', stamp)} disk ({have_gb:.0f} GB free): {line}", flush=True)
            done.append(line)
    for root in sorted(emptied):
        popen(["sh", "-c", f"rm -rf {shlex.quote(str(root / '.trash'))}/*"], stdout=subprocess.DEVNULL,
              stderr=subprocess.DEVNULL, start_new_session=True)
    return done
