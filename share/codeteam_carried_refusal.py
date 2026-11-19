"""The refusal text for a landing set that carries other open work orders' commits (Orc-Codegraph #4653, D559)."""
from collections.abc import Mapping, Sequence


def carried_refusal(names: Sequence[str], carried: Mapping[str, str], queued: Sequence[str]) -> str:
    """names: the set's work orders; carried: {work order: its first commit the set holds}; queued: those of carried
    already in the landing queue, which the set waits for instead of taking along."""
    joinable = [wo for wo in carried if wo not in queued]
    what = ", ".join(f"{wo} ({commit[:10]})" for wo, commit in carried.items())
    how = [f"land them together: land {names[0]} {' '.join(f'--with {wo}' for wo in [*names[1:], *joinable])}"
           ] if joinable else []
    how += [f"{wo} is already queued: run land again once it lands" for wo in queued]
    return (f"{', '.join(names)} carries unlanded commits of open work order {what}; another work order's commits "
            f"land only with it. " + "; ".join(how) + ".")
