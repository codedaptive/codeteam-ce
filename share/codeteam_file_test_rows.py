"""A failed Stage 6 run's test entries, one per failing vitest file, so each finding goes to the zone owning that file.

A suite with one command and no `FAILED ZONES|MODULES` line would otherwise be recorded as one `suite` failure, which
goes to the orchestrator with no names. vitest's summary names every failing file and test, so the run's entries are
one per failing file (with its failing tests), a pass for each open name no longer failing (which closes its finding),
and, on a hung run, the `suite` entry beside them.
"""

from codeteam_vitest_failures import vitest_failures

# The same cap as the run-wide failing list: a finding's text names at most this many tests.
_MOST = 20


def _failing_files(text: str) -> dict[str, list[str]]:
    """Each failing file vitest's summary in text names, in order, with its failing tests ([] for a file that failed
    as a whole)."""
    files: dict[str, list[str]] = {}
    for file, test in vitest_failures(text):
        files.setdefault(file, []).extend([test] if test is not None else [])
    return files


def file_test_rows(res: dict, open_names: list[str]) -> list[dict]:
    """One fail entry per failing file vitest's summary in res["tail"] names, in order, then a pass for each open name
    not among them (a hung run's open `suite` aside), then on a hung run the `suite` entry; [] for a run that passed
    or names no vitest failure."""
    if res["result"] not in ("fail", "hung"):
        return []
    files = _failing_files(res.get("tail", ""))
    if not files:
        return []
    tests = [{"name": file, "result": "fail", "seconds": None, "failing": names[:_MOST]}
             for file, names in files.items()]
    hung = res["result"] == "hung"
    tests.extend({"name": name, "result": "pass", "seconds": None} for name in open_names
                 if name not in files and not (hung and name == "suite"))
    if hung:
        tests.append({"name": "suite", "result": "hung", "seconds": res.get("seconds")})
    return tests
