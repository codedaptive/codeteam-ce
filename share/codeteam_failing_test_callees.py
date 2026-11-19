"""The files a failing test calls into, from a CodeGraph index.

The rule: the culprit's call path is the stack "plus CodeGraph callees" of the failing test, where the
product's repo has a CodeGraph index, "with no index, the stack alone". The tree tested is queried when it has its own
index, else the product's repo when it has one; the batch's tree is a checkout of the repo, so a path relative to the
repo's root names the same file in the tree when the tree has it. Only `codegraph callees` is run: an index command
(or `--fresh`, which syncs) would change a shared index from inside a landing. Its `-j` output is one object whose
"targets" (the symbol's definitions) and "callees" lists hold objects with a "filePath", relative to the indexed root
or absolute (codegraph's CLI, `callees --json`). A callee carries no line, so it matches an entry at file level. The
query asks for CODEGRAPH_LIMIT callees, and the rule for when an answer is complete lives with that limit in
codeteam_codegraph_complete.py; an incomplete answer is not used, that test is matched on its stack alone, and it is
named in the result. A parametrized pytest name loses its trailing case id (`test_y[1.5]` asks `test_y`), so the
function is asked and a "." or "/" inside the id does not split it; several cases of one function cost one query.
Only a symbol that is an identifier is asked: a vitest name such as `<file> > describe > test` splits to a fragment
that is no symbol, and asking would cost a query under the itest lock and name the test incomplete for nothing.
"""

import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from codeteam_codegraph_complete import CODEGRAPH_LIMIT, codegraph_complete

CALLEES_TIMEOUT_S = 60      # one query on a built index answers in seconds; a hung server must not hold the lock


def _run(cmd: list[str]) -> str | None:
    """cmd's stdout, or None when it fails, times out or cannot start."""
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=CALLEES_TIMEOUT_S)
    except (subprocess.TimeoutExpired, OSError):
        return None
    return done.stdout if done.returncode == 0 else None


def _paths(output: str | None) -> list[str] | None:
    """The filePath of every target and callee in codegraph's JSON output; None when the answer is not complete (no
    output, bad JSON, or codegraph_complete false)."""
    try:
        data = json.loads(output or "")
    except ValueError:
        return None
    if not codegraph_complete(data, "callees"):
        return None
    return [node["filePath"] for node in data.get("targets", []) + data["callees"] if "filePath" in node]


def _in_tree(tree: Path, root: Path, raw: str) -> str | None:
    """raw (relative to the queried root, or absolute) as a path relative to tree when that file exists, else None:
    a path inside tree is made relative to it, any other path inside root keeps its path relative to root."""
    path = (root / raw).resolve()
    base = tree.resolve() if path.is_relative_to(tree.resolve()) else root.resolve()
    if not path.is_relative_to(base):
        return None
    relative = str(path.relative_to(base))
    return relative if (tree / relative).is_file() else None


def _index_root(tree: Path, repo: Path | None) -> Path | None:
    """tree when it has a .codegraph index, else repo when it has one, else None."""
    return next((root for root in (tree, repo) if root is not None and (root / ".codegraph").is_dir()), None)


def _function_name(test: str) -> str:
    """test without "()" and without a trailing bracketed case id: a name ending in "]" is cut from the "[" that opens
    that trailing group, the first "[" after the first "::" (a path may hold "[", a function or class name never does),
    or the first "[" when there is no "::". The id may itself hold "::", "/", "." or "["."""
    name = test.removesuffix("()")
    if not name.endswith("]"):
        return name
    head, sep, tail = name.partition("::")
    return head + sep + tail.split("[", 1)[0] if sep else head.split("[", 1)[0]


def _test_paths(test: str, root: Path, run: Callable[[list[str]], str | None],
                asked: dict[str, list[str] | None]) -> list[str] | None:
    """The paths CodeGraph gives for test's symbol, the last part after "::", "/" or "." of its _function_name; []
    with no query when the symbol is not an identifier; None when the answer is not complete. asked holds each
    symbol's answer, so a symbol is queried once per call."""
    symbol = re.split(r"::|/|\.", _function_name(test))[-1]
    if not re.fullmatch(r"[A-Za-z_]\w*", symbol):
        return []
    if symbol not in asked:
        asked[symbol] = _paths(run(["codegraph", "callees", symbol, "-p", str(root), "-j", "-l", str(CODEGRAPH_LIMIT)]))
    return asked[symbol]


def failing_test_callees(tree: Path, tests: list[str], run: Callable[[list[str]], str | None] | None = None,
                         repo: Path | None = None) -> tuple[list[list], list[str]]:
    """([[relpath, None]] for the files of tree that the failing tests' symbols call, each once, from tree's index or
    else repo's; the names of the tests whose answer was incomplete, in input order, each once); ([], []) when neither
    has an index. A test's symbol is the last part of its name after "::", "/" or "." ("()" and a trailing "[case id]"
    dropped first); only an identifier is asked, each symbol once per call, and a test whose symbol is not one gets no
    query and is not named. Every test whose symbol's answer is incomplete is named, so cases sharing a function are
    each named."""
    root = _index_root(tree, repo)
    if root is None:
        return [], []
    run = run or _run
    frames, incomplete, asked = [], [], {}
    for test in tests:
        paths = _test_paths(test, root, run, asked)
        if paths is None and test not in incomplete:
            incomplete.append(test)
        for raw in paths or []:
            relative = _in_tree(tree, root, raw)
            if relative is not None and [relative, None] not in frames:
                frames.append([relative, None])
    return frames, incomplete
