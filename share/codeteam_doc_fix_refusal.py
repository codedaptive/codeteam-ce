"""Why doc-fix refuses to commit a work order tree's delta, if it does.

"Only changes to code go back through the entire process." doc-fix commits a reviewer's comment and doc corrections,
and test moves into integration or validation, onto the reviewed tip, so it refuses, in this order: a tree not on its
branch (a land's set merge left in it); a HEAD that is not the reviewed tip (the commit would carry unreviewed commits
past review); nothing to commit; any changed or new file outside the work order's zone; any test moved into the unit
group (code in v1); and any file the comment-only detector reads as code that is not a test move, each named so the
reviewer files those as findings. The caller gathers the facts from git; this decides from them alone.
"""


def _listed(head: str, paths: list[str]) -> str:
    return head + "\n  " + "\n  ".join(paths)


def doc_fix_refusal(facts: dict) -> str | None:
    """The first reason doc-fix refuses the delta `facts` describe, or None when it may commit.

    facts: "wo", "branch", "on_branch" (HEAD is the branch and no merge is under way), "head", "tip" (the reviewed
    tip), "changed" (changed or new files), "outside" (those outside the zone's walls), "code" (those read as code,
    less the test moves into integration or validation), and optionally "unit_moves" (the paths of tests moved into the
    unit group).
    """
    wo = facts["wo"]
    if not facts["on_branch"]:
        return f"{wo}: its tree is not on its branch {facts['branch']} (a land's set merge?); put it back first"
    if facts["head"] != facts["tip"]:
        return (f"{wo}: its tree's HEAD {facts['head'][:10]} is not its reviewed tip {facts['tip'][:10]}; "
                "doc-fix commits only on the reviewed tip")
    if not facts["changed"]:
        return f"{wo}: nothing to commit"
    if facts["outside"]:
        return _listed(f"{wo}: changes files outside its zone (walls):", facts["outside"])
    if facts.get("unit_moves"):
        return _listed(f"{wo}: moves tests into the unit group (code in v1: no landing step runs one unit test without "
                       "a build; file it as a finding):", facts["unit_moves"])
    if facts["code"]:
        return _listed(f"{wo}: not comment- or doc-only (these read as code; file them as findings):",
                       facts["code"])
    return None
