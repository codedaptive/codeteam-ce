"""land-one: land one checked queue entry now (rule 13).

An entry that owes its integration step runs it alone, as a batch of one (queue_batch), then Stage 4 on a pass; on a
failure whose frames its diff holds it is sent back, and one whose failure matches no entry lands, the failure
becoming a fix finding (batch_verdict). Any other entry lands under the queue lock (land_entry). `land`:
codeteam-land's names (Lock, prune_queue, entry_path, die, land_entry, queue_batch, entry_members, REFUSED, GATE).
"""

import json
import sys
from pathlib import Path


def _refusal(wo: str, entry: dict) -> str | None:
    """Why queue_batch would not land this owed entry (its _still_ready test), or None."""
    if entry.get("hold"):
        return f"{wo} is held: release it with land-hold {wo} first"
    if entry.get("review") != "land":
        return f"{wo}'s review is {entry.get('review')!r}, not 'land': it waits for its review"
    return None


def _outcome(team, wo: str, path: Path, entry: dict, land) -> int:
    """0 when every member landed; REFUSED while the entry is still queued; GATE when it left the queue unlanded."""
    if all(team.wo_file(member).with_suffix(".landed.json").exists() for member, _ in land.entry_members(entry)):
        return 0
    if path.exists():
        print(f"{wo} stays queued: its integration step did not run to a landing", file=sys.stderr)
        return land.REFUSED
    print(f"{wo} left the queue without every member landing: sent back", file=sys.stderr)
    return land.GATE


def land_one(team, wo: str, land) -> int:
    """Land wo's queue entry; the exit code for land-one."""
    with land.Lock(team):
        land.prune_queue(team)
        path = land.entry_path(team, wo) or land.die(f"{wo} is not queued")
        entry = json.loads(path.read_text())
        if entry.get("integration") != "owed":
            return land.land_entry(team, path)
    refusal = _refusal(wo, entry)
    if refusal:
        print(refusal, file=sys.stderr)
        return land.REFUSED
    # queue_batch takes the itest lock and then the queue lock itself, so it runs after this Lock is released.
    try:
        land.queue_batch(team, [path], land)
    except FileNotFoundError:
        pass                            # the entry left the queue meanwhile; _outcome reads where it went
    return _outcome(team, wo, path, entry, land)
