"""The repo frames a failing step's output names, for queue-run's culprit search.

The rule: "Find the culprit from the record: the failing test's file:line and its call path (stack plus
CodeGraph callees), matched against each entry's diff." This reads the stack part: Python tracebacks
(`File "p", line n`) and the `path:line[:col]` form pytest, rustc (`--> p:l:c`), Rust panics and Swift errors print.
Only files that exist inside the tree count, so library and toolchain frames never match an entry's diff.
"""

import re
from pathlib import Path

FRAME = re.compile(r'File "(?P<py>[^"]+)", line (?P<pyline>\d+)'
                   r'|(?<![\w./-])(?P<path>[\w./-]+\.\w+):(?P<line>\d+)(?::\d+)?')


def _inside(tree: Path, raw: str) -> str | None:
    """raw as a path relative to tree when it names an existing file inside it, else None."""
    path = Path(raw) if Path(raw).is_absolute() else tree / raw
    try:
        relative = path.resolve().relative_to(tree.resolve())
    except ValueError:
        return None
    return str(relative) if path.is_file() else None


def failure_frames(text: str, tree: Path) -> list[list]:
    """[[relpath, line]] for every repo frame in text, in order of appearance, each once."""
    frames = []
    for match in FRAME.finditer(text):
        raw, line = (match["py"], match["pyline"]) if match["py"] else (match["path"], match["line"])
        relative = _inside(tree, raw)
        if relative is not None and [relative, int(line)] not in frames:
            frames.append([relative, int(line)])
    return frames
