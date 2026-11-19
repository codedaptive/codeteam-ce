"""Refresh team.json's lanes for each team manifest a promote changed.

The zone guard reads each lane's owns from the team's team.json, and team.json's lanes follow the manifest only when
`codeteam sync-lanes` (or a role render) runs. A promote that changes a manifest under codeteam's own checkout must
therefore refresh that team's team.json, or the guard keeps enforcing the old walls. Nothing restarts.
"""

from collections.abc import Callable, Iterable
from pathlib import Path
import subprocess

# A sync reads one manifest and writes one JSON file; a minute means it is stuck, and the promote has already landed.
TIMEOUT_SECONDS = 60
# Lines of a failed sync's output carried into the message: enough for the reason, short enough for a NOTE.
TAIL_LINES = 3


def refresh_lanes(repo: Path, files: Iterable[str], manifests: Iterable[Path], codeteam: Path,
                  run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> list[str]:
    """Run `codeteam sync-lanes` for each manifest whose repo-relative path is in files (as git diff --name-only
    prints them). Returns one message per failed manifest, [] when all succeed; never raises, because the base has
    already moved when this runs."""
    root = Path(repo).resolve()
    changed = set(files)
    messages = []
    for manifest in _changed_manifests(root, changed, manifests):
        try:
            result = run([str(codeteam), "sync-lanes", str(manifest)], capture_output=True, text=True,
                         timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            messages.append(f"team.json lanes not refreshed for {manifest}: sync-lanes took over {TIMEOUT_SECONDS} s")
            continue
        except OSError as ex:
            messages.append(f"team.json lanes not refreshed for {manifest}: sync-lanes could not start: {ex}")
            continue
        if result.returncode != 0:
            tail = "\n".join(((result.stderr or "") + (result.stdout or "")).strip().splitlines()[-TAIL_LINES:])
            messages.append(f"team.json lanes not refreshed for {manifest}: sync-lanes exited {result.returncode}: "
                            f"{tail}")
    return messages


def _changed_manifests(root: Path, changed: set[str], manifests: Iterable[Path]) -> list[Path]:
    """The manifests, deduplicated by resolved path, that sit inside root and whose root-relative path is in changed."""
    seen = set()
    selected = []
    for manifest in manifests:
        resolved = Path(manifest).resolve()
        if resolved in seen or not resolved.is_relative_to(root):
            continue
        seen.add(resolved)
        if resolved.relative_to(root).as_posix() in changed:
            selected.append(manifest)
    return selected
