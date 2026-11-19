"""The new-side line numbers a two-dot diff adds, per file (D473).

codegraph blast finds its own merge base, which on a criss-cross history is one of several, so its added lines can
include landed work. A two-dot diff from a base that holds all landed work has only the work order's own lines;
intersecting blast's lines with these keeps the work order's own.
"""
import re

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def diff_plus_lines(git, base: str, head: str = "HEAD") -> dict[str, set[int]] | None:
    """{path: new-side numbers of '+' lines} in `git diff base head`; a deleted file has no entry. None when git
    fails. `git(*args, env=None)` returns an object with .returncode and .stdout."""
    try:
        result = git("diff", "-U0", "--no-color", "--no-ext-diff", base, head)
    except OSError:
        return None
    if result.returncode:
        return None
    lines: dict[str, set[int]] = {}
    path, n = None, 0
    for line in (result.stdout or "").splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
            if path is not None:
                lines.setdefault(path, set())
        elif hunk := _HUNK.match(line):
            n = int(hunk.group(1))
        elif path is not None and line.startswith("+"):
            lines[path].add(n)
            n += 1
        elif line.startswith(" "):     # a context line, from a diff run with context, is on the new side too
            n += 1
    return lines
