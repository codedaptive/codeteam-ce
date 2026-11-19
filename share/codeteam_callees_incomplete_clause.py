"""The clause a failing step's report carries when CodeGraph's callees answer was incomplete (D569).

A failing test whose CodeGraph callees answer was incomplete is matched against the batch's diffs on its stack alone,
and the reports say so: queue_batch sets result["callees_incomplete"] to those tests' names. Both reports of a failing
step, the fix finding (batch_fix_finding) and the send-back REQUEST (integration_send_back), use this clause so they
say the same thing.
"""


def callees_incomplete_clause(result: dict) -> str:
    """"" when the step result names no test with incomplete callees; else the clause naming them."""
    if not result.get("callees_incomplete"):
        return ""
    return (f"CodeGraph's callees were incomplete for {', '.join(result['callees_incomplete'])}; "
            "matched on the stack alone")
