"""The cause, inside a queue-run batch, of an entry's merge conflict (rule 13; D554, creator #4628).

batch_tree merges a batch's entries in the order queue-run gives (priority, then queue order, D575), so an entry
can conflict with one merged ahead of it in the same batch, which has not landed yet and which conflicting_landings
therefore cannot name. The conflict NOTE names those entries' work orders too.
"""

from collections.abc import Callable, Hashable


def batch_causes(group: list[tuple[Hashable, dict]], key: Hashable, files: list[str], conflicted: set,
                 members: Callable[[dict], list[tuple[str, str]]]) -> list[str]:
    """The work orders (members(entry)) of the entries ahead of key in group, not conflicted themselves, whose
    "files" include one of files."""
    causes = []
    for earlier, entry in group:
        if earlier == key:
            break
        if earlier not in conflicted and set(files) & set(entry.get("files", [])):
            causes += [wo for wo, _ in members(entry)]
    return causes
