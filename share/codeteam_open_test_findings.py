"""Which findings a Stage 5 recheck may add to or close.

A recheck's passing test closes its open test finding and a failing one adds the recheck's M to it. Validation's
findings are Stage 6's to close, never a recheck's. With batching, one recheck covers a whole batch, so this choice
sits on its own, out of apply_recheck_findings, to keep that function small.
"""

from collections.abc import Iterable


def open_test_findings(findings: Iterable[dict]) -> list[dict]:
    """The open findings that name a test, except those filed by validation, in their given order."""
    return [fix for fix in findings if fix["state"] == "open" and "test" in fix and fix.get("by") != "validation"]
