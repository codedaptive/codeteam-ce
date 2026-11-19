"""The REQUEST that sends a work order back from queue-run's integration step.

A batch entry whose diff holds code on a failure's path (batch_culprits: the failing steps' frames matched against
each entry's changed files and lines) goes back to its zone's coordinator with the matched frames, the
failing steps, their failing tests and their log paths, as the batch rule asks ("sent back to the zone that owns the failing
code, by file and line").
"""

from codeteam_callees_incomplete_clause import callees_incomplete_clause


def _failed(results: list[dict]) -> list[str]:
    """One line per step that did not pass: its name and outcome, failing tests, log path or last lines, and which
    failing tests were matched on their stack alone because CodeGraph's callees were incomplete."""
    failed = []
    for result in results:
        if result["outcome"] == "PASS":
            continue
        line = f"{result['name']} ({result['outcome'].lower()})"
        if result.get("failing"):
            line += f": failing tests {', '.join(result['failing'])}"
        if result.get("log"):
            line += f"; log {result['log']}"
        elif result.get("tail"):
            line += f"; last lines: {' | '.join(result['tail'])}"
        if clause := callees_incomplete_clause(result):
            line += f"; {clause}"
        failed.append(line)
    return failed


def integration_send_back(wos: list[str], integration: str, M: str, results: list[dict], frames: list[list]) -> str:
    """The message for work orders wos, tested at commit M on the tip of branch integration (the branch every work
    order tree is cut from, so the failure is the batch's own); results are the step results of that run (a step
    that did not pass may carry "failing" test names, "log", "tail" and "callees_incomplete"); frames are the
    [path, line] frames of the failure that the work orders' diff holds (line None: the file only)."""
    where = ", ".join(path if line is None else f"{path}:{line}" for path, line in frames)
    matched = f" Its diff holds code on the failure's path: {where}." if frames else ""
    return (f"{', '.join(wos)} did not land: Stage 2's integration step failed at queue-run, tested on {integration}'s "
            f"tip with the queue's other ready work orders, at {M[:10]}.{matched} Failed: "
            f"{'; '.join(_failed(results))}. Nothing of it landed and it is out of the queue; its tree is kept. Fix it "
            "in the same work order tree and run land again.")
