"""The orc's git command judged by the repository top it acts on (D587)."""
from git_top import git_top
from orc_package_refusal import orc_package_refusal


def orc_judge_top(sub: str, gcwd: str | None, where: list[str], manifest: str, codeteam_home: str) -> str | None:
    """D587: the refusal of the orc's git sub when the repository top of a folder git acts on
    (where, in order; the first refusal is returned) holds a code package folder, else None. An
    unknown folder (gcwd None) passes."""
    if gcwd is None:
        return None
    for w in where:
        top = git_top(w)
        why = orc_package_refusal(top, manifest, codeteam_home)
        if why:
            return f"git {sub} in `{top}`: {why}"
    return None
