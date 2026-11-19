"""folder_kind: the test kind a file's folder names (the test kinds rule).

A test under a folder named exactly unit, integration or validation is that kind; the deepest such folder wins, so
tests/integration/validation/t.py is a validation test. The file name never counts. A test under no such folder is
unnamed: zone-tool and the pytest plugin treat it as a unit test that runs only in the unit run.
"""
from pathlib import PurePosixPath

KINDS = ("unit", "integration", "validation")


def folder_kind(rel: str) -> str | None:
    """The deepest folder of rel's parent named unit, integration or validation; None if none."""
    return next((part for part in reversed(PurePosixPath(rel).parent.parts) if part in KINDS), None)
