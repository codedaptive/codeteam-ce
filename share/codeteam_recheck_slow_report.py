"""What a Stage 5 recheck's slow-tests flag reports (R-26, D566; creator #4708 deciding Orc-Codeteam #4684).

The ruling: "A recheck opens a slow follow-up only if the same work order's Stage 2 was also over 15 minutes;
otherwise the flag line says load." Each work order a recheck covers has its Stage 2 test time on its landed record
("stage2_tests_s"); one without it counts as not over the limit. When some covered work order's Stage 2 was over, the
follow-up opens through report_slow_tests with the newest such work order as its source and the files those work
orders changed (D548's routing). Otherwise no follow-up opens and the orchestrator's NOTE says it was load, with each
covered work order's Stage 2 figure.
"""

from codeteam_recheck_slow_source import recheck_slow_source


def _figure(wo: str, seconds: float | None) -> str:
    return f"{wo} Stage 2 not recorded" if seconds is None else f"{wo} Stage 2 {seconds / 60:.1f} min"


def _followup(team, land, flag: dict, row: dict, recs: dict, slow: list[str]) -> None:
    """The follow-up, sourced from the newest slow work order, with the slow work orders' files unioned in order."""
    head, source = recheck_slow_source(row | {"wo": slow[-1]}, recs.get)
    changed = list(dict.fromkeys(file for wo in slow for file in recs[wo].get("files", [])))
    land.report_slow_tests(team, flag, head, "Stage 5", source, changed)


def _load(team, land, flag: dict, row: dict, recs: dict) -> None:
    """The orchestrator's NOTE that the flag was load; an error is logged, never raised."""
    try:
        head, _ = recheck_slow_source(row, recs.get)
        figures = ", ".join(_figure(wo, rec.get("stage2_tests_s")) for wo, rec in recs.items())
        load = (f"load, not a follow-up: no work order it covers had Stage 2 tests over "
                f"{land.SLOW_TESTS_LIMIT_S // 60} min ({figures})")
        team.notify(team.c("orchestrator", "orc"), "NOTE", land.slow_tests_note(head, "Stage 5", flag, load))
    except Exception as ex:
        team.log({"time": land.now(), "slow_tests_error": f"{type(ex).__name__}: {ex}"})


def recheck_slow_report(team, land, flag: dict | None, row: dict) -> None:
    """Nothing when flag is None. Else a follow-up (land.report_slow_tests) when a work order the row covers
    (row["batch"] or [row["wo"]]) had Stage 2 tests over land.SLOW_TESTS_LIMIT_S, sourced from the newest such one
    with their changed files unioned in order; otherwise the load NOTE to the orchestrator. `land`: codeteam-land's
    names."""
    if flag is None:
        return
    recs = {wo: land.landed_rec(team, wo) or {} for wo in row.get("batch") or [row["wo"]]}
    slow = [wo for wo, rec in recs.items() if (rec.get("stage2_tests_s") or 0) > land.SLOW_TESTS_LIMIT_S]
    if slow:
        _followup(team, land, flag, row, recs, slow)
    else:
        _load(team, land, flag, row, recs)
