"""Tell the orchestrator, once, that a work order's tree is not a git work tree (codeteam-jj #4406, D497).

codeteam-land's clean_idle skips such a tree. A folder left holding only .codegraph/ once made its git call end
queue-run, and launchd restarted it into the same exit; now the tree is skipped and the record's `not_a_git_tree`
mark keeps the note from repeating every pass.
"""
from collections.abc import Callable
from pathlib import Path


def not_git_note(team, rec: dict, wo: str, tree: Path, error: str, now: Callable[[], str]) -> None:
    """Unless `rec` already carries `not_a_git_tree`: mark it with `now()`, save it with `team.save_wo`, and send the
    orchestrator ([land].orchestrator, else orc) a NOTE naming work order `wo`, `tree` and git's `error` (first 160
    characters)."""
    if rec.get("not_a_git_tree"):
        return
    rec["not_a_git_tree"] = now()
    team.save_wo(rec)
    team.notify(team.c("orchestrator", "orc"), "NOTE",
                f"Work order {wo}: its tree {tree} is not a git work tree ({error[:160]}), so the landing runner's "
                "idle clean skips it. Move the folder aside, or retire the work order.")
