"""Stage 2's check that a landing set carries no other open work order's unlanded commits (Orc-Codegraph #4653, D559:
an orc work order cut on host's tip landed alone after host bounced at Stage 3, and took host's commits onto landing
past their review). Land them together, or wait for one already queued."""
from collections.abc import Callable, Iterable

from codeteam_carried_order import Order
from codeteam_carried_orders import carried_orders
from codeteam_carried_refusal import carried_refusal


def carried_check(team, records: list[dict], open_records: Callable[[object], Iterable[tuple[object, dict]]],
                  entry_path: Callable[[object, str], object]) -> str | None:
    """The refusal for the set whose work order records are given, or None when it carries nothing. team is the land
    tool's Team (its `landing` branch is read); open_records(team) gives the team's (record file, record) pairs and
    entry_path(team, wo) is truthy for a work order in the landing queue (the land tool's own functions)."""
    names = [rec["wo"] for rec in records]
    carried = carried_orders([Order.of(rec, team.landing) for rec in records],
                             [Order.of(rec, team.landing) for _, rec in open_records(team) if rec.get("wo") not in names])
    return carried_refusal(names, carried, [wo for wo in carried if entry_path(team, wo)]) if carried else None
