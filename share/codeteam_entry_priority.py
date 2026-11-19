"""A landing queue entry's priority class, the order queue-run takes it in.

0: a work order of the entry fixes a finding of severity 1 or 2. 2: its work orders fix findings and every one is
severity 3. 1: anything else (new work, slow-tests follow-ups, a fix whose finding is no longer found). Only a
record's "fixes" counts: "slow_fixes" are follow-ups, not findings.
"""

from collections.abc import Iterable, Mapping


def entry_priority(recs: Iterable[Mapping], severity: Mapping[str, int]) -> int:
    """recs: the entry's work order records; severity: finding id to severity. An id missing from severity, or whose
    severity is not an int, is unknown and does not count."""
    known = [severity[fid] for rec in recs for fid in rec.get("fixes") or []
             if isinstance(severity.get(fid), int)]
    if any(level in (1, 2) for level in known):
        return 0
    return 2 if known and all(level == 3 for level in known) else 1
