"""Send back a batch entry the failure's frames point at.

The batch rule: "A failure in a batch is sent back to the zone that owns the failing code, by file and line." The entry
leaves the queue, its members lose "queued" and get the batch run's Stage 2 rows, its zone's coordinator gets one
REQUEST naming the failing steps that matched it (run["results"], as batch_verdict filters them) and the frames
its diff holds (integration_send_back), landed.log gets "integration failed", and its tree is kept for the fix.
"""

from pathlib import Path


def batch_send_back(team, land, item: tuple[Path, dict], run: dict, frames: list[list]) -> None:
    """Take item out of the queue, record run["rows"] on its members and tell the first member's zone, naming the
    matched frames. `land`: codeteam-land's names."""
    path, entry = item
    with land.Lock(team):
        path.unlink(missing_ok=True)
        recs = [team.wo(wo) for wo, _ in land.entry_members(entry)]
        for rec in recs:
            rec.pop("queued", None)
            rec.setdefault("stage2", []).extend(run["rows"])
            team.save_wo(rec)
    wos = [rec["wo"] for rec in recs]
    team.notify(land.zone_session(team, recs[0]["zone"]), "REQUEST",
                land.integration_send_back(wos, team.integration, run["commit"], run["results"], frames))
    team.log({"time": land.now(), "wos": wos, "result": "integration failed"})
