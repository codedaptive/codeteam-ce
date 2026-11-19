"""The lines a work order changed, per file, from `git diff -U0` (rule 13; D554, creator #4663).

queue-run matches a failing batch's frames against each entry's diff "by file and line" (rule 13). This reads the new
side of each hunk: `+c,d` covers lines c to c+d-1, and a pure deletion (d = 0) is kept as its anchor line c, where the
removed code was. A deleted file has no new side, so it is keyed by its old path with no ranges, which matches any
line of it.
"""

import re

HUNK = re.compile(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@")


def _header_path(line: str) -> str:
    """The path of a "--- a/x" or "+++ b/x" header line, its a/ or b/ prefix dropped."""
    path = line[4:].rstrip("\n")
    return path[2:] if path[:2] in ("a/", "b/") else path


def diff_ranges(diff: str) -> dict[str, list[tuple[int, int]]]:
    """{path: [(start, end)]} of the new-side lines each file's hunks cover, in diff order."""
    ranges: dict[str, list[tuple[int, int]]] = {}
    current = None
    lines = diff.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("--- ") and index + 1 < len(lines) and lines[index + 1].startswith("+++ "):
            new = lines[index + 1]
            current = None if new == "+++ /dev/null" else _header_path(new)
            ranges.setdefault(current or _header_path(line), [])
        elif current and (hunk := HUNK.match(line)):
            start, count = int(hunk[1]), int(hunk[2] if hunk[2] is not None else 1)
            ranges[current].append((start, start + max(count, 1) - 1))
    return ranges
