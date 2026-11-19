"""share/codeteam_carried_orders.py (Orc-Codegraph #4653, D559): which other open work orders a landing set carries
commits of. Unit tests (rule 11): a pure function over commit lists and cut times."""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_carried_order import Order
from codeteam_carried_orders import carried_orders

EARLY = datetime.fromisoformat("2026-11-17T09:00:00-06:00")
LATE = datetime.fromisoformat("2026-11-17T10:00:00-06:00")
HOST = Order("host", ["c2", "c1"], EARLY)
COMMENT = Order("comment", ["c3", "c2", "c1"], LATE)    # seed-schemaless-comment: cut on host's tip, then its own c3
OTHER = Order("other", ["c9"], EARLY)


def test_a_work_order_holding_all_of_anothers_commits_carries_it():
    assert carried_orders([COMMENT], [HOST, OTHER]) == {"host": "c2"}


def test_the_work_order_cut_on_it_is_not_carried_by_its_host():
    assert carried_orders([HOST], [COMMENT, OTHER]) == {}


def test_after_they_grow_apart_the_shared_commits_are_the_earlier_cut_ones():
    moved_host = Order("host", ["c4", "c2", "c1"], EARLY)    # host fixed its finding forward after comment took c2
    assert carried_orders([COMMENT], [moved_host]) == {"host": "c2"}
    assert carried_orders([moved_host], [COMMENT]) == {}


def test_cut_in_the_same_second_the_name_first_owns_the_shared_commits():
    alpha = Order("alpha", ["a1", "s1"], EARLY)
    beta = Order("beta", ["b1", "s1"], EARLY)
    assert carried_orders([beta], [alpha]) == {"alpha": "s1"}
    assert carried_orders([alpha], [beta]) == {}


def test_the_first_shared_commit_in_the_other_work_orders_order_is_named():
    assert carried_orders([Order("m", ["a", "b", "c"], LATE)], [Order("w", ["c", "b"], EARLY)]) == {"w": "c"}


def test_two_work_orders_on_the_same_commits_carry_each_other():
    twin = Order("twin", ["c2", "c1"], LATE)
    assert carried_orders([twin], [HOST]) == {"host": "c2"}
    assert carried_orders([HOST], [twin]) == {"twin": "c2"}


def test_nothing_shared_carries_nothing():
    assert carried_orders([Order("m", ["c3"], LATE)], [HOST]) == {}
    assert carried_orders([Order("m", [], LATE)], [HOST]) == {}
    assert carried_orders([COMMENT], [Order("host", [], EARLY)]) == {}


def test_any_member_of_the_set_can_carry_and_several_are_named_in_name_order():
    members = [Order("m1", ["b", "x"], LATE), Order("m2", ["a", "y"], LATE)]
    others = [Order("zeta", ["b"], EARLY), Order("alpha", ["a"], EARLY)]
    assert list(carried_orders(members, others)) == ["alpha", "zeta"]
