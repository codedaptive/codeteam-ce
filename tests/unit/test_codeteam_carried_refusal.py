"""share/codeteam_carried_refusal.py (Orc-Codegraph #4653, D559): the refusal text for a landing set that carries other
open work orders' commits. Unit tests (rule 11): a pure function over names."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_carried_refusal import carried_refusal


def test_a_carried_work_order_not_queued_is_taken_along():
    assert carried_refusal(["comment"], {"host": "0123456789abcdef"}, []) == (
        "comment carries unlanded commits of open work order host (0123456789); another work order's commits land "
        "only with it. land them together: land comment --with host.")


def test_a_carried_work_order_already_queued_is_waited_for():
    assert carried_refusal(["comment"], {"host": "c2"}, ["host"]) == (
        "comment carries unlanded commits of open work order host (c2); another work order's commits land only with "
        "it. host is already queued: run land again once it lands.")


def test_the_sets_other_members_stay_in_the_land_line():
    text = carried_refusal(["a", "b"], {"host": "c2", "late": "c7"}, ["late"])
    assert text.startswith("a, b carries unlanded commits of open work order host (c2), late (c7);")
    assert "land them together: land a --with b --with host; late is already queued" in text
