"""The orc's git command judged by the path one pathspec names (D587)."""
import os

from orc_package_refusal import orc_package_refusal
from orc_pathspec import orc_pathspec


def orc_judge_pathspec(sub: str, a: str, gcwd: str | None, manifest: str, codeteam_home: str) -> str | None:
    """D587: the refusal of the orc's git sub on pathspec a when the path it names is in or holds a
    code package folder, else None. A variable, a relative path with no known folder and exclude
    magic pass."""
    if "$" in a or (gcwd is None and not os.path.isabs(a)):
        return None
    p = orc_pathspec(a, gcwd or "/")
    why = p and orc_package_refusal(p, manifest, codeteam_home)
    return f"git {sub} on `{a}`: {why}" if why else None
