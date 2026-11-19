"""One base commit for a tree whose history meets landed work at more than one commit (D473).

A tree cut at integration that merged an unlanded M, measured against a landing that merges M and integration, has
two incomparable merge bases (a criss-cross). Any one of them leaves the other's landed lines counted as the work
order's own. A commit that merges all the independent bases (a chain of two-parent merges when there are more than
two), with their merged tree, holds every landed line, so a two-dot diff from it to the tip is the work order's own
change only.

The commit is built with a fixed identity and date, so the same bases always give the same hash. Nothing references
it: it is only diffed against, and git's gc can remove it once unreferenced objects expire. Bases whose trees
conflict cannot be merged without a person; then there is no merged base and the caller keeps its one-base answer.
"""
import os

_IDENTITY = {
    "GIT_AUTHOR_NAME": "codeteam-land",
    "GIT_AUTHOR_EMAIL": "codeteam-land@localhost",
    "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
    "GIT_COMMITTER_NAME": "codeteam-land",
    "GIT_COMMITTER_EMAIL": "codeteam-land@localhost",
    "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
}


def _words(result) -> list[str]:
    """The ids git printed, or none when it failed. A result without stdout printed nothing."""
    return (getattr(result, "stdout", "") or "").split() if result.returncode == 0 else []


def _first(result) -> str | None:
    return next(iter(_words(result)), None)


def merged_base(git, tip: str, refs: list[str]) -> str | None:
    """A commit merging every independent merge base of `tip` with `refs`, or None when there are fewer than two
    such bases or any git step fails. `git(*args, env=None)` returns an object with .returncode and .stdout."""
    try:
        bases = []
        for ref in refs:
            bases.extend(_words(git("merge-base", "--all", tip, ref)))
        if not bases:
            return None
        heads = _words(git("merge-base", "--independent", *dict.fromkeys(bases)))
        if len(heads) < 2:
            return None
        env = dict(os.environ, **_IDENTITY)
        cur = heads[0]
        for head in heads[1:]:
            tree = _first(git("merge-tree", "--write-tree", cur, head))
            if tree is None:
                return None
            cur = _first(git("commit-tree", tree, "-p", cur, "-p", head, "-m", "codeteam-land merged base",
                             env=env))
            if cur is None:
                return None
        return cur
    except OSError:
        return None
