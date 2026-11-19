"""Which roots can hold repo integration tests.

RITs are written against a kit's public surface, so they live in a test target or test folder, never inside a
library's own modules: a crate root would run its library's integration tests through widgets's test_one.sh, which ORs a name
filter with `integration::`. A root that holds no file naming the selector at a word start gets no step, since a
filtered run of nothing passes having proved nothing, and `inherit_` must not count as `rit_`. The check reads text,
not test names: a selector named only in a comment still makes a step that runs no test.
"""
import os
import re
from pathlib import Path

TEST_SEGMENTS = {"tests", "Tests", "__tests__"}
SKIPPED = {"target", ".build", "node_modules"}


def _names(folder: Path, pattern: re.Pattern) -> bool:
    for where, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in SKIPPED and not d.startswith(".")]
        for name in files:
            try:
                if pattern.search((Path(where) / name).read_text(errors="replace")):
                    return True
            except OSError:
                continue
    return False


def rit_roots(tree, roots: list[str], selector: str) -> list[str]:
    """The roots, in their order, with a path segment `tests`, `Tests` or `__tests__` and a file under them (not in
    target/, .build/, node_modules/ or a dot folder) that holds `selector` at a word start."""
    pattern = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(selector))
    return [root for root in roots
            if TEST_SEGMENTS & set(root.strip("/").split("/")) and _names(Path(tree) / root, pattern)]
