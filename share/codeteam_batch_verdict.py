"""Decide a failed batch from its record: who goes back, who lands.

The rule: "no bisecting a failed batch. Find the culprit from the record: the failing test's file:line and
its call path (stack plus CodeGraph callees), matched against each entry's diff. That entry goes back to its zone and
the rest land. Re-running parts of the batch to find it is ruled out." Each entry's diff is its members' diffs from
the batch's base (integration's tip) merged; each failing step's frames come from the run (queue_batch) and are
matched on their own, so an entry goes back with only the steps that point at it. The batch rule's "the rest of the batch
stands": every entry no step matched lands, and each failing step that matched no entry becomes a fix finding for
the zone that owns it (batch_fix_finding), even when other steps matched.
"""

from pathlib import Path

from codeteam_batch_culprits import batch_culprits
from codeteam_batch_fix_finding import batch_fix_finding
from codeteam_batch_landed import batch_landed
from codeteam_batch_send_back import batch_send_back
from codeteam_diff_ranges import diff_ranges


def _entry_changes(team, land, entry: dict, base: str) -> dict[str, list[tuple[int, int]]]:
    """The entry's changed ranges per file over all its members; a file one member deleted stays whole ([])."""
    changes: dict[str, list[tuple[int, int]]] = {}
    for _, tip in land.entry_members(entry):
        for path, ranges in diff_ranges(land.out(team.repo, "diff", "-U0", f"{base}...{tip}")).items():
            whole = path in changes and not changes[path] or not ranges
            changes[path] = [] if whole else changes.get(path, []) + ranges
    return changes


def _routes(results: list[dict], changes: dict[str, dict]) -> tuple[dict[str, list[tuple[dict, list]]], list[dict]]:
    """Each failing step matched on its own: {entry key: [(step, its frames that matched the entry)]}, in step order,
    and the failing steps no entry matched."""
    matched: dict[str, list[tuple[dict, list]]] = {}
    unmatched = []
    for result in (result for result in results if result["outcome"] != "PASS"):
        culprits = batch_culprits(result.get("frames", []), changes)
        for key, hits in culprits.items():
            matched.setdefault(key, []).append((result, hits))
        if not culprits:
            unmatched.append(result)
    return matched, unmatched


def _frames(steps: list[tuple[dict, list]]) -> list[list]:
    """The matched frames of an entry's steps, in order, each once."""
    frames = []
    for _, hits in steps:
        frames.extend(frame for frame in hits if frame not in frames)
    return frames


def batch_verdict(team, land, kept: list[tuple[Path, dict]], run: dict) -> bool:
    """Send back each entry of kept that a failing step's frames match, naming only those steps; land the rest; open
    a finding for each failing step no entry matched. land_entry's refusal gives False. `land`: codeteam-land's
    names."""
    matched, unmatched = _routes(run["results"], {str(path): _entry_changes(team, land, entry, run["base"])
                                                  for path, entry in kept})
    for item in kept:
        if steps := matched.get(str(item[0])):
            batch_send_back(team, land, item, run | {"results": [step for step, _ in steps]}, _frames(steps))
    landed = batch_landed(team, land, [item for item in kept if str(item[0]) not in matched], run)
    if unmatched:
        batch_fix_finding(team, land, kept, run | {"results": unmatched})
    return landed
