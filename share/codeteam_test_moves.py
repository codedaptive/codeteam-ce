"""Which changes in a delta are test moves, and what code is left once they are set aside.

A test move changes which group a test runs in and nothing else. It is either an exact rename (R100) of a test file
into a group folder, or a test file in no group folder whose only change is its `TEST_GROUP` gate (inside a
group folder a changed gate would run nowhere). The file NAME says what a test file is, never its folder: a bare
basename through is_test_file, or the full path through the team's globs. The group comes from folder_kind, or for a
gate change from the one group word its added lines name. A move into integration or validation is not code; a move
into unit is still code in v1. The caller runs git; this decides from its output alone.
"""
import re
from collections.abc import Callable, Iterable
from fnmatch import fnmatchcase

from codeteam_folder_kind import folder_kind
from codeteam_test_file import is_test_file

GROUP_WORD = re.compile(r"\b(unit|integration|validation)\b")


def _rows(raw: str) -> list[tuple[str, str, str, str, str]]:
    """(old mode, new mode, status, old path, new path) of each `git diff --raw -z` row; one path means old == new."""
    fields = raw.split("\0")
    rows, i = [], 0
    while i < len(fields) and fields[i]:
        old_mode, new_mode, _, _, status = fields[i].lstrip(":").split(" ")
        two = status[0] in "RC"
        old, new = fields[i + 1], fields[i + 2 if two else i + 1]
        rows.append((old_mode, new_mode, status, old, new))
        i += 3 if two else 2
    return rows


def _named_test(path: str, globs: list[str]) -> bool:
    return is_test_file(path.rsplit("/", 1)[-1]) or any(fnmatchcase(path, glob) for glob in globs)


def _gate_group(added: list[str], removed: list[str]) -> str | None:
    """The one group word the added lines name, when every changed line is a TEST_GROUP gate line."""
    if not added + removed or any("TEST_GROUP" not in line for line in added + removed):
        return None
    words = {word for line in added for word in GROUP_WORD.findall(line)}
    return words.pop() if len(words) == 1 else None


def _move(row, changed_lines, globs: list[str]) -> dict | None:
    old_mode, new_mode, status, old, new = row
    if status == "R100" and _named_test(old, globs) and _named_test(new, globs):
        group = folder_kind(new)
    elif status == "M" and old_mode == new_mode and _named_test(new, globs) and folder_kind(new) is None:
        group = _gate_group(*changed_lines(new))
    else:
        return None
    return {"path": new, "from": old, "to": new, "group": group} if group else None


def test_moves(raw: str, changed_lines: Callable[[str], tuple[list[str], list[str]]], code: list[str],
               globs: Iterable[str] = ()) -> tuple[list[dict], list[str]]:
    """The test moves in `raw` (`git diff --raw -z -M100% --no-abbrev`), in its order, and `code` without the paths
    of every move into integration or validation.

    changed_lines(path) gives a modified file's (added, removed) lines; it is called only for a test file's M row with
    its mode unchanged and no group folder. globs are the team's `[land] test_globs`.
    """
    globs = list(globs)
    moves = [move for row in _rows(raw) if (move := _move(row, changed_lines, globs))]
    gone = {path for move in moves if move["group"] != "unit" for path in (move["from"], move["to"])}
    return moves, [path for path in code if path not in gone]
