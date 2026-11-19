"""The commit a queue-run batch is tested at.

Starting from integration's tip, the branch every work order tree is cut from (so each entry is tested only with
code already proven), each entry's member tips are merged in the order queue-run gives (priority, then queue order),
as Stage 4 merges them, without moving landing. An entry whose merge conflicts goes back (conflict) and the
chain goes on from where it was before that entry, so the rest of the batch stands.
"""

from collections.abc import Callable, Hashable


def batch_tree(base: str, entries: list[tuple[Hashable, list[tuple[str, str]]]],
               merge_one: Callable[[str, str, str], tuple[str | None, list[str]]],
               conflict: Callable[[Hashable, list[str], str], None]) -> tuple[str, list[Hashable]]:
    """entries: (key, [(wo, tip), ...]). merge_one(cur, wo, tip) gives (merge commit, []) or (None, conflicting
    files); conflict(key, files, wo) is told of a conflicting entry. Returns (the last merge commit, or base when none
    merged; the keys of the entries merged whole, in order)."""
    cur, kept = base, []
    for key, members in entries:
        start = cur
        for wo, tip in members:
            commit, files = merge_one(cur, wo, tip)
            if commit is None:
                conflict(key, files, wo)
                cur = start
                break
            cur = commit
        else:
            kept.append(key)
    return cur, kept
