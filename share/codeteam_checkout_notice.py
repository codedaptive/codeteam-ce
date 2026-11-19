"""One NOTE per episode of failed itest checkouts at queue-run's integration step (rule 13; D554, creator #4628).

A checkout that fails is the machine, not the work orders: queue-run lands nothing, sends nothing back and tries
again each pass, as Stage 5 does (D371). The episode's marker file is written with its first NOTE, so later passes
that still fail send nothing new; queue-run removes it after the next checkout that works.
"""

import json
from collections.abc import Callable
from pathlib import Path


def checkout_notice(marker: Path, wos: list[str], commit: str, error: str, when: str,
                    notify: Callable[[str], None]) -> bool:
    """With no marker: write it and notify once, naming the work orders and git's error; True. Else nothing; False."""
    if marker.exists():
        return False
    marker.write_text(json.dumps({"time": when, "commit": commit, "wos": wos, "error": error}) + "\n")
    notify(f"queue-run's integration step could not check out the itest tree at {commit[:10]} for work orders "
           f"{', '.join(wos)}: {' '.join(error.splitlines())}. Nothing landed and nothing was sent back; every entry "
           "stays queued and queue-run tries again each pass until the checkout works (git's error above names the "
           "cause).")
    return True
