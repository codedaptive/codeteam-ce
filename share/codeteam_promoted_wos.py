"""The work orders a promotion from `old` to `new` carries (D600).

A landing row carries the merge hash it landed at and the work orders it landed; a promotion carries the rows whose
hash `new` contains and `old` does not. codeteam-land's promoted_notices names them in its notices. The caller passes
the landing rows and the ancestry test, so this stays a function of its arguments.
"""
from collections.abc import Callable


def promoted_wos(rows: list[dict], is_ancestor: Callable[[str, str], bool], old: str, new: str) -> list[str]:
    """The work orders of every row in `rows` whose hash is an ancestor of `new` and not of `old`, in row order and
    each row's own order; a row with no hash is skipped."""
    return [wo for row in rows if row.get("hash") and is_ancestor(row["hash"], new)
            and not is_ancestor(row["hash"], old) for wo in row.get("wos", [])]
