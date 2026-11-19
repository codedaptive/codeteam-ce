"""Whether a review finding holds the work it was found in.

"A security finding, whoever files it, is recorded with its severity, location and owner, and raised to the
orchestrator. The work it was found in carries on: it is committed, lands and promotes on the private branches as
normal. The fix is a fix-forward order in the owning zone." So at Stage 3 a security finding never sends a work order
back, never refuses its next land, and is not closed by the work order landing; it stays open until its fix-forward
lands with --fixes. Every other kind holds as before.
"""

SECURITY = "security"


def finding_holds(finding: dict) -> bool:
    """False for a security finding (finding["kind"] == "security"), True for any other kind."""
    return finding.get("kind") != SECURITY
