"""HostReservation: a time-capped hold on a validation host, which Stage 6 honours by starting no new run there.

Lab's timed runs on the validation machine start only when no land-check runs
there and are rerun when acme's Stage 6 adds a row during them, and acme's Stage 6 adds one about every 7 minutes,
so a long timed run rarely finishes clean. The timed-run step takes a reservation for its run; while it holds, a
team whose Stage 6 host is that host starts no new validation there (a run already going finishes), so only its
promotion waits. A reservation ends when it is released or when its time runs out, whichever comes first, and never
lasts longer than MAX_MINUTES, so a step that dies before it releases holds nothing for long.
One file per host, `<run>/host-reservations/<host>.json`: {"host", "by", "reason", "since", "until"} (epoch seconds).
"""
import json
import os
import re
import time
from pathlib import Path

MAX_MINUTES = 90          # a timed run takes about 20 minutes; this bounds how long a promotion can wait
HOST_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class HostReservation:
    """Reservations under `run_dir` (codeteam's run/ folder, shared by every team on this machine)."""

    def __init__(self, run_dir: Path):
        self.folder = Path(run_dir) / "host-reservations"

    def _path(self, host: str) -> Path:
        if not HOST_NAME.fullmatch(host or ""):
            raise ValueError(f"not a host name: {host!r}")
        return self.folder / f"{host}.json"

    def held(self, host: str, now: float) -> dict | None:
        """The live reservation of `host`, or None. An unreadable file holds nothing: it must not stop Stage 6."""
        try:
            row = json.loads(self._path(host).read_text())
            return row if float(row["until"]) > now else None
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def take(self, host: str, minutes: float, by: str, reason: str, now: float) -> dict:
        """Reserve `host` for `minutes` from `now`. Taking it again by the same holder replaces the old end time.
        Raises ValueError for a time outside 0 < minutes <= MAX_MINUTES or a host another holder has reserved."""
        if not 0 < minutes <= MAX_MINUTES:
            raise ValueError(f"a reservation lasts more than 0 and at most {MAX_MINUTES} minutes, not {minutes:g}")
        live = self.held(host, now)
        if live and live.get("by") != by:
            raise ValueError(f"{host} is reserved by {live.get('by')} until {_clock(live['until'])}: {live.get('reason')}")
        row = {"host": host, "by": by, "reason": reason, "since": now, "until": now + minutes * 60}
        path = self._path(host)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(row) + "\n")
        tmp.replace(path)
        return row

    def release(self, host: str, by: str, now: float) -> bool:
        """End `by`'s reservation of `host` (or an expired one). False when another holder's live one stands."""
        live = self.held(host, now)
        if live and live.get("by") != by:
            return False
        self._path(host).unlink(missing_ok=True)
        return True


def _clock(epoch: float) -> str:
    return time.strftime("%H:%M", time.localtime(float(epoch)))
