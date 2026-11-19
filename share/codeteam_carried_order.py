"""One open work order as the carried-commits check weighs it (Orc-Codegraph #4653, D559)."""
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import NamedTuple

from codeteam_unlanded_commits import unlanded_commits

_CUT_FIRST = datetime.min.replace(tzinfo=timezone.utc)


class Order(NamedTuple):
    """A work order's name, its commits not on landing (newest first) and when it was cut."""
    wo: str
    commits: Sequence[str]
    cut: datetime

    @classmethod
    def of(cls, rec: dict, landing: str) -> "Order":
        """The order for a work order record. wo-retire's stand-in record for a tree wo-cut never recorded has no cut
        time, and counts as cut first."""
        cut = datetime.fromisoformat(rec["cut"]) if "cut" in rec else _CUT_FIRST
        return cls(rec["wo"], unlanded_commits(rec.get("tree"), landing), cut)
