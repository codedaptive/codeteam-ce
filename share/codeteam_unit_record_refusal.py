"""The text of Stage 2's refusal when a work order has no clean unit record (D495).

With CODETEAM_KINDS_BY_NAME=1 the landing tool runs no unit tests: the lead proves its file changes with unit tests
in its own tree, and Stage 2 takes that record. When the record is missing, the refusal has to say which record was
looked for and how to make it, so the lead can fix it without reading the landing tool.
"""
from collections.abc import Iterable


def unit_record_refusal(wo: str, zone: str, tip: str, keys: Iterable[str] | None, commands: Iterable[str]) -> str:
    """The refusal for work order wo of zone, whose tree is at tip: the record keys looked for (None: they could
    not be read) and the unit test commands that make the record, one per line."""
    looked = ("the record keys could not be read" if keys is None
              else "looked under " + ", ".join(f"'{key}'" for key in keys))
    return "\n".join([
        f"REFUSED {wo}: Stage 2 of a team with CODETEAM_KINDS_BY_NAME=1 runs no unit tests; it takes the lead's "
        f"clean unit record instead.",
        f"No clean unit record for zone {zone} at {tip[:10]} ({looked}).",
        "In the work order's tree, with every change committed, run:",
        *commands,
        "Then land again.",
    ])
