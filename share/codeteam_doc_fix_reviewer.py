"""Whether a session may run doc-fix on a work order.

"Only changes to code go back through the entire process." A comment or doc finding is fixed by the Stage 3 reviewer
itself with `codeteam-land doc-fix`, so the command runs only for a session that is a pending reviewer of the work
order's pending Stage 3 review; anyone else, or a work order with no such review, is refused with the reason.
"""


def doc_fix_reviewer(row: dict | None, session: str | None) -> str | None:
    """None when `session` is a pending reviewer of the pending Stage 3 review `row`; else the refusal text."""
    if not session:
        return "set CODETEAM_SESSION to your session name"
    if not row or row.get("stage") != 3 or row.get("state") != "pending":
        return f"{(row or {}).get('wo') or 'it'} has no pending Stage 3 review"
    if row.get("reviewers", {}).get(session) != "pending":
        return f"{session} is not a pending Stage 3 reviewer of {row['wo']}"
    return None
