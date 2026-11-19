"""Which other open work orders a landing set carries commits of (Orc-Codegraph #4653, D559): a work order cut on
another's tip holds that one's commits, and landing it alone takes them onto landing past their own Stage 3."""
from collections.abc import Iterable

from codeteam_carried_order import Order


def _takes(member: Order, other: Order) -> bool:
    """Whether member holds commits that are other's. It does when it holds all of other's, so two work orders on the
    very same commits carry each other and land together; not when other holds all of its own and more (other was cut
    on it); and when the two have grown apart past what they share, the shared commits are the work order's cut first,
    the name first on a tie (host moved on after seed-schemaless-comment took its tip)."""
    mine, theirs = set(member.commits), set(other.commits)
    if not mine & theirs:
        return False
    if theirs <= mine:
        return True
    return not mine <= theirs and (other.cut, other.wo) < (member.cut, member.wo)


def carried_orders(members: Iterable[Order], others: Iterable[Order]) -> dict[str, str]:
    """{work order: the first of its commits, in its own order, that the set also holds} for every work order in others
    whose commits a member of the set takes, in name order."""
    members = list(members)
    held = {commit for member in members for commit in member.commits}
    return {other.wo: next(commit for commit in other.commits if commit in held)
            for other in sorted(others, key=lambda o: o.wo) if any(_takes(member, other) for member in members)}
