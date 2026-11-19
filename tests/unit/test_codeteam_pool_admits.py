import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_pool_admits import pool_admits  # noqa: E402


SHARES = {"land": (2, 0), "full": (1, 1), "post": (1, 2), "pre": (1, 2), "dev": (1, 0)}


def cfg(budget):
    return SimpleNamespace(shares=SHARES, budget=budget)


def test_under_guaranteed_share_admits_over_budget():
    heads = {"dev": {"cost": 4}}
    assert pool_admits("dev", heads, Counter(), 10, cfg(8)) is True


def test_borrowing_fits_budget_exactly():
    heads = {"dev": {"cost": 2}}
    assert pool_admits("dev", heads, Counter(dev=1), 6, cfg(8)) is True
    assert pool_admits("dev", heads, Counter(dev=1), 7, cfg(8)) is False


def test_reservation_of_class_under_its_share_counts_against_budget():
    heads = {"dev": {"cost": 1}, "full": {"cost": 4}}
    assert pool_admits("dev", heads, Counter(dev=1), 4, cfg(8)) is False
    assert pool_admits("dev", heads, Counter(dev=1), 3, cfg(8)) is True


def test_class_at_its_share_reserves_nothing():
    heads = {"dev": {"cost": 1}, "full": {"cost": 4}}
    assert pool_admits("dev", heads, Counter(dev=1, full=1), 7, cfg(8)) is True


def test_ceiling_zero_is_no_ceiling():
    heads = {"dev": {"cost": 1}}
    assert pool_admits("dev", heads, Counter(dev=7), 7, cfg(8)) is True


def test_ceiling_reached_refuses_with_room():
    heads = {"post": {"cost": 1}}
    assert pool_admits("post", heads, Counter(post=2), 2, cfg(8)) is False
    assert pool_admits("post", heads, Counter(post=1), 1, cfg(8)) is True
