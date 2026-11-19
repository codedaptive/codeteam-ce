"""shell_skip_kind: whether zone-tool test-one's by-name run skips a shell test (the test kinds rule).

With CODETEAM_KINDS_BY_NAME=1 a shell test runs only in its own kind's run. A script with no fixed kind (it reads
the group itself, shell_test_kind None) runs in every group. Kept out of zone-tool's _test_one_plan so that
function does not grow another branch.
"""
from pathlib import Path

from codeteam_shell_kind import shell_test_kind


def shell_skip_kind(path: Path, rel: str, group: str) -> str | None:
    """The kind the script at path (rel from the repo root) belongs to when it is not group; None when it runs."""
    kind = shell_test_kind(path, rel)
    return None if kind in (None, group) else kind
