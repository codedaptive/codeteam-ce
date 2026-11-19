"""A failure no batch entry's diff explains becomes a fix finding.

The batch rule: "A failure in a batch is sent back to the zone that owns the failing code, by file and line; the rest of the
batch stands." When the failing steps' frames match no entry, every entry lands (batch_verdict) and each failing step
goes to the zone that owns it as a fix-forward finding, the way a Stage 5 recheck failure does (open_recheck_finding
in codeteam-land): a step that already has an open test finding gets the batch commit as its "batch_commit" and
nothing new is sent. The batch commit never lands, so it stays out of "Ms": Stage 7 holds a promotion for a finding
whose "Ms" holds an ancestor of the candidate, and a pruned unlanded commit would make that ancestry check refuse
every promotion. A finding opens with "Ms" empty; Stage 5's recheck of the landed work adds a landed M, closes it or
leaves it. Nothing is closed here. Bookkeeping must not
undo a landing that already happened, so an error is logged, never raised.
"""

from pathlib import Path

from codeteam_callees_incomplete_clause import callees_incomplete_clause
from codeteam_open_test_findings import open_test_findings
from codeteam_step_zone import step_zone


def _what(team, result: dict, commit: str) -> str:
    """The finding's text: where the step failed, why the batch landed, its failing tests and log, and which failing
    tests were matched on their stack alone because CodeGraph's callees were incomplete."""
    what = (f"{result['name']} fails in Stage 2's batch run at {commit[:10]} on {team.integration}'s tip; no work "
            "order of the batch changed a file on the failure's path, so they landed")
    if result.get("failing"):
        what += f"; failing tests: {', '.join(result['failing'])}"
    if result.get("log"):
        what += f"; log: {result['log']}"
    if clause := callees_incomplete_clause(result):
        what += f"; {clause}"
    return what


def _record(team, land, items: list[tuple[Path, dict]], run: dict, result: dict,
            wos: list[str]) -> tuple[str, str] | None:
    """Set run["commit"] as the step's open test finding's "batch_commit", or open one on the newest entry's
    feature; the session and REQUEST text for a new finding, else None. The caller holds FindingsLock."""
    name, commit = result["name"], run["commit"]
    existing = next((fix for fix in open_test_findings(land.all_findings(team)) if fix["test"] == name), None)
    if existing:
        feature = existing["id"].rsplit("#", 1)[0]
        listed = land.load_findings(team, feature)
        next(fix for fix in listed if fix["id"] == existing["id"])["batch_commit"] = commit
        land.save_findings(team, feature, listed)
        return None
    zone = step_zone(name, land.is_test_step, lambda step: land.step_owner(team, step)) or "orc"
    newest = land.entry_members(items[-1][1])[0][0]
    feature = land.feature_of(land.landed_rec(team, newest) or team.wo(newest))
    findings = land.load_findings(team, feature)
    fid, what = f"{feature}#{len(findings) + 1}", _what(team, result, commit)
    findings.append({"id": fid, "time": land.now(), "by": "queue-run", "also": [], "feature": feature, "wos": wos,
                     "zone": zone, "where": name, "severity": 2, "kind": "test", "what": what, "belongs": "",
                     "state": "open", "fixed_by": None, "closed": None, "reason": None, "test": name,
                     "Ms": [], "batch_commit": commit})
    land.save_findings(team, feature, findings)
    return (land.zone_session(team, zone),
            f"FIX-FORWARD {fid} | zone {zone} | test {name} | M {commit[:10]} | work orders {', '.join(wos)} | "
            f"{what}. Route as a work order; it lands with codeteam-land {team.manifest} land <wo> --fixes {fid}.")


def batch_fix_finding(team, land, items: list[tuple[Path, dict]], run: dict) -> None:
    """Record each failing step of run["results"] as a test finding against the landed batch items and send each new
    one to its zone. `land`: codeteam-land's names."""
    wos = [wo for _, entry in items for wo, _ in land.entry_members(entry)]
    try:
        with land.FindingsLock(team):
            requests = [_record(team, land, items, run, result, wos)
                        for result in run["results"] if result["outcome"] != "PASS"]
        for request in filter(None, requests):
            team.notify(request[0], "REQUEST", request[1])
    except Exception as ex:
        team.log({"time": land.now(), "wos": wos, "batch_finding_error": f"{type(ex).__name__}: {ex}"})
