import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_class_pick import class_pick  # noqa: E402


SHARES = {"land": (2, 0), "full": (1, 1), "post": (1, 2), "pre": (1, 2), "dev": (1, 0)}


def cfg(budget):
    return SimpleNamespace(shares=SHARES, budget=budget)


def running(cls, cost):
    return {"class": cls, "cost": cost, "state": "running"}


def test_nothing_waiting_picks_nothing():
    assert class_pick({"land": None, "dev": None}, [], cfg(8)) is None


def test_first_class_in_start_order_wins():
    post, dev = {"cost": 1, "id": "post"}, {"cost": 1, "id": "dev"}
    assert class_pick({"post": post, "dev": dev}, [], cfg(8)) is post


def test_class_past_its_share_is_skipped_for_a_later_one_that_fits():
    full, dev = {"cost": 4, "id": "full"}, {"cost": 1, "id": "dev"}
    # full is at its ceiling of 1; dev is under its guaranteed share
    assert class_pick({"full": full, "dev": dev}, [running("full", 4)], cfg(8)) is dev


def test_borrowing_class_waits_when_budget_is_used():
    dev = {"cost": 2, "id": "dev"}
    assert class_pick({"dev": dev}, [running("dev", 3), running("land", 4)], cfg(8)) is None
    assert class_pick({"dev": dev}, [running("dev", 3), running("land", 3)], cfg(8)) is dev


def test_unpriced_running_job_counts_as_zero():
    dev = {"cost": 2, "id": "dev"}
    assert class_pick({"dev": dev}, [running("dev", None), running("land", 6)], cfg(8)) is dev


def test_reservation_for_a_later_class_under_its_share_holds_room():
    post, dev = {"cost": 3, "id": "post"}, {"cost": 4, "id": "dev"}
    # post has one running (its share), dev none: dev reserves 4, so post's 3 does not fit beside 2 used
    assert class_pick({"post": post, "dev": dev}, [running("post", 2)], cfg(8)) is dev
