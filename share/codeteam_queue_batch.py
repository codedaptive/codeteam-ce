"""Stage 2's integration step once for every ready entry that owes it, then Stage 4 (the batch rule).
In the itest tree, under its lock: integration's tip with each entry's members merged in the order queue-run
gives (priority, then queue order, batch_tree), the compile steps, then, only when all pass, the integration steps
for the batch's zones and files (integration's tip: every work order tree is cut from it, so no entry fails for landed
code it did not write; Stage 5 tests landed work). The batch is tested once; no part of it is run again. A pass lands each entry still ready (batch_landed); a failure is decided from the run's record (batch_verdict):
each failing step's repo frames and its tests' CodeGraph callees, kept on the result as "frames" while the tree is still
under the lock, and the tests whose callees answer was incomplete, as "callees_incomplete" when there are any. A failed
checkout lands nothing and sends nothing back, one NOTE per episode (checkout_notice). `land`: codeteam-land's names,
the team-bound parts.
"""

import json
from contextlib import nullcontext
from pathlib import Path

from codeteam_batch_causes import batch_causes
from codeteam_batch_landed import batch_landed
from codeteam_batch_slow_entry import batch_slow_entry
from codeteam_batch_verdict import batch_verdict
from codeteam_checkout_notice import checkout_notice
from codeteam_failing_test_callees import failing_test_callees
from codeteam_failure_frames import failure_frames

CHECKOUT_MARKER = "queue-batch-checkout.json"     # an episode of failed checkouts, already told (checkout_notice)


def _union(items: list[tuple[Path, dict]], key: str) -> list[str]:
    return sorted({value for _, entry in items for value in entry.get(key, [])})


def _rows(land, results: list[dict]) -> list[dict]:
    return [row for result in results for row in land.stage2_record([result], result.get("group"))]


def _frames(team, land, tree: Path, text: str) -> tuple[list[list], list[str]]:
    """A failing step's stack frames in the repo, then its failing tests' callees (tree's index, else the repo's),
    each once; and the failing tests whose callees answer was incomplete (_run_steps keeps them as
    "callees_incomplete")."""
    callees, incomplete = failing_test_callees(tree, land.failing_test_names(text), repo=team.repo)
    frames = []
    for frame in failure_frames(text, tree) + callees:
        if frame not in frames:
            frames.append(frame)
    return frames, incomplete


def _run_steps(team, land, tree: Path, items: list[tuple[Path, dict]], run: dict) -> list[dict]:
    """Compile steps, then integration steps only if all compiled; a failing step's frames (and "callees_incomplete"
    when any of its tests' callees answers was incomplete), the run's Stage 2 rows (run["rows"], their test records
    kept), its test steps' slow-test measure (run["tests_s"], land.test_run_s) and logs kept. The checkout worked: the
    episode ends."""
    (team.dir / CHECKOUT_MARKER).unlink(missing_ok=True)
    compile_steps, test_steps = land.recheck_steps(team, tree, _union(items, "zones"), _union(items, "files"))
    env = land.team_env(team, "integration")
    results = land.step_results(tree, compile_steps, env, concurrent=False, keep_text=True, group="compile")
    if all(result["outcome"] == "PASS" for result in results):
        results.extend(land.step_results(tree, test_steps, env, keep_text=True, group="integration"))
    for result in results:
        if result["outcome"] != "PASS" and "text" in result:
            result["frames"], incomplete = _frames(team, land, tree, result["text"])
            if incomplete:
                result["callees_incomplete"] = incomplete
    run["tests_s"] = land.test_run_s(results, land.is_test_step, land.step_run_seconds)
    run["rows"] = land.keep_stage2_records(team.dir, f"batch-{run['commit'][:10]}", _rows(land, results))
    land.keep_recheck_logs(team, run["commit"], results)
    return results


def _checkout_failed(team, land, kept: list[tuple[Path, dict]], run: dict) -> None:
    """Mark run as a failed checkout, so nothing lands or goes back, and tell the orchestrator once per episode."""
    run["checkout_failed"] = True
    checkout_notice(team.dir / CHECKOUT_MARKER, [wo for _, entry in kept for wo, _ in land.entry_members(entry)],
                    run["commit"], run["results"].error, land.now(),
                    lambda text: team.notify(land.zone_session(team, "orc"), "NOTE", text))


def _tested(team, land, group: list[tuple[Path, dict]], run: dict) -> tuple[bool, list[tuple[Path, dict]]]:
    """Build the group's commit on integration's tip and test it, keeping base, commit and results in run."""
    entries = dict(group)
    member = {wo: (entry["base"], team.wo(wo)) for _, entry in group for wo, _ in land.entry_members(entry)}
    conflicted = set()

    def conflict(path: Path, files: list[str], wo: str) -> None:
        causes = batch_causes(group, path, files, conflicted, land.entry_members)
        conflicted.add(path)
        with land.Lock(team):
            landed = land.conflicting_landings(team, entries[path]["base"], run["base"], files)
            recs = [member[w][1] for w, _ in land.entry_members(entries[path])]
            land.landing_conflict(team, path, recs, files, wo, list(dict.fromkeys(landed + causes)))

    with land.itest_lock(team.dir):
        run["base"] = land.out(team.repo, "rev-parse", f"refs/heads/{team.integration}")
        commit, kept_paths = land.batch_tree(
            run["base"], [(path, land.entry_members(entry)) for path, entry in group],
            lambda cur, wo, tip: land.merge_landing_member(team, member[wo][0], cur, member[wo][1], tip), conflict)
        kept = [(path, entries[path]) for path in kept_paths]
        if not kept:
            return False, []
        run["commit"] = commit
        run["results"] = land.recheck_at(nullcontext(), lambda: land.itest_checkout(team, commit),
                                         lambda tree: _run_steps(team, land, tree, kept, run), land.CheckoutFailed,
                                         lambda ex: ex)
    if isinstance(run["results"], land.CheckoutFailed):
        _checkout_failed(team, land, kept, run)
        return False, []
    return all(result["outcome"] == "PASS" for result in run["results"]), kept


def _report_slow(team, land, items: list[tuple[Path, dict]], run: dict) -> None:
    """The whole batch's slow-tests flag, every work order in the head, the batch's files, and as source the
    work order and zone of the entry that brought the slowest step into the run (batch_slow_entry)."""
    flag = land.slow_tests_flag(run["results"])
    chosen = batch_slow_entry(flag, [entry for _, entry in items], lambda name: land.step_owner(team, name))
    land.report_slow_tests(team, flag,
                           ", ".join(wo for _, entry in items for wo, _ in land.entry_members(entry)), "Stage 2",
                           {"wo": chosen["wo"], "zone": team.wo(chosen["wo"])["zone"], "stage": 2,
                            "commit": run["commit"]}, _union(items, "files"))


def queue_batch(team, paths: list[Path], land) -> bool:
    """Test the ready queue files paths (queue-run's order: priority, then queue order) as one batch, once, and
    land or send back each entry; False when the itest checkout failed (the entries stay queued) or land_entry refused
    an entry."""
    items = [(path, json.loads(path.read_text())) for path in paths]
    run = {}
    label = ", ".join(wo for _, entry in items for wo, _ in land.entry_members(entry))
    with land.stage_admit("Stage 2", f"integration step of {label}"):
        passed, kept = _tested(team, land, items, run)
        if not kept:
            return not run.get("checkout_failed")
        _report_slow(team, land, items, run)
        return (batch_landed if passed else batch_verdict)(team, land, kept, run)
