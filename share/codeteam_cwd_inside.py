"""Whether a process works inside a tree (D599): codeteam-land's clean_idle leaves such a tree alone, since a Stage 2
step, a build or a lead's own command is still using it (a request lead's own process sits in its coordinator's
folder, so it counts only while one of its commands runs there). Pure, so it is a function of its arguments only."""
from collections.abc import Iterable


def cwd_inside(tree: str, cwds: Iterable[str]) -> bool:
    """True when some working folder in `cwds` is `tree` itself or lies below it (a sibling sharing its name as a
    prefix does not count)."""
    return any(cwd == tree or cwd.startswith(tree + "/") for cwd in cwds)
