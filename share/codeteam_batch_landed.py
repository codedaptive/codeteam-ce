"""Land the entries of a tested batch that stand.

The batch rule: "the rest of the batch stands." Every member of each entry gets the batch run's Stage 2 rows (run["rows"],
pointing at the test records kept for the run) before Stage 4, so a landed record says which run proved it, and its
Stage 2 test time ("stage2_tests_s", the measure): the larger of its own land run's and the batch run's
(run["tests_s"]), which a Stage 5 recheck reads to tell a slow work order from load. Under the
queue lock, each entry still ready when read again lands through land_entry in the order queue-run gives (priority,
then queue order); a Stage 4 conflict sends that entry back and the next goes on, and any other refusal stops
the landing.
"""

import json
from pathlib import Path


def _still_ready(path: Path) -> bool:
    """Read under Lock: the entry is still queued, not held and reviewed "land"."""
    if not path.exists():
        return False
    entry = json.loads(path.read_text())
    return not entry.get("hold") and entry.get("review") == "land"


def batch_landed(team, land, items: list[tuple[Path, dict]], run: dict) -> bool:
    """Record run["rows"] and the larger of "stage2_tests_s" and run["tests_s"] on every member of items, then land
    each entry still ready; False when land_entry refuses one for anything but a conflict. `land`: codeteam-land's
    names."""
    for _, entry in items:
        for wo, _ in land.entry_members(entry):
            rec = team.wo(wo)
            rec.setdefault("stage2", []).extend(run["rows"])
            rec["stage2_tests_s"] = round(max(rec.get("stage2_tests_s") or 0, run.get("tests_s", 0)), 1)
            team.save_wo(rec)
    with land.Lock(team):
        for path, _ in items:
            if _still_ready(path) and land.land_entry(team, path) not in (0, land.CONFLICT):
                return False
    return True
