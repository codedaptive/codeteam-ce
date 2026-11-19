"""The paths a lane owns besides its zone folder, read fresh on every hook process.

team.json follows the manifest: codeteam refreshes it when a promote changes the manifest, so a lane's
walls move without a restart. CODETEAM_OWNS is the copy taken at
launch; it is the fallback when team.json says nothing usable about the lane. An "owns" of null or []
is an answer (the lane owns nothing more), not a reason to fall back.
"""
import json
from pathlib import Path


def _clean(entries) -> tuple[str, ...]:
    """Each entry as text, without surrounding whitespace or slashes; empties dropped."""
    return tuple(s for s in (str(x).strip().strip("/") for x in entries) if s)


def lane_own_owns(team_json: Path | None, lane: str, fallback) -> tuple[str, ...]:
    """lanes[lane]["owns"] from team_json, or the fallback when it has none to give. Never raises."""
    # A non-object document, lanes or entry fails the subscript with TypeError; None as the path too.
    try:
        owns = json.loads(Path(team_json).read_text(encoding="utf-8"))["lanes"][lane]["owns"]
    except (TypeError, OSError, ValueError, KeyError):
        return _clean(fallback)
    if owns is None:
        return ()
    return _clean(owns) if isinstance(owns, list) else _clean(fallback)
