"""`codeteam sync-lanes <manifest>`: make team.json's lanes follow the manifest without rendering any role.

The zone guard reads a lane's walls from team.json, so the landing tool runs this when a promote changes a manifest; rendering roles there would overwrite a v2 team's role text. bin/codeteam passes its
own functions in, so this file imports nothing from it.
"""
import sys
from collections.abc import Callable


def sync_lanes_command(t, manifest, discover_lanes: Callable, sync_lanes: Callable, load_team: Callable) -> None:
    """Refresh t's team.json lanes from its manifest. A manifest whose lanes cannot be discovered exits naming the
    manifest, where sync_lanes alone would skip silently."""
    try:
        discover_lanes(t, t.base)
    except SystemExit as ex:
        sys.exit(f"sync-lanes: cannot read the lanes of {manifest}: {ex.code}")
    sync_lanes(t, load_team(t))
