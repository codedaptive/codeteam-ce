import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_promoted_wos import promoted_wos

# History: a1 <- a2 (old) <- b1 <- b2 (new). Each tip's ancestors, itself included, as git merge-base --is-ancestor.
CONTAINS = {"old": {"a1", "a2"}, "new": {"a1", "a2", "b1", "b2"}}


def is_ancestor(commit: str, tip: str) -> bool:
    return commit in CONTAINS[tip]


def test_rows_only_in_new_are_kept_with_each_rows_wos_in_order():
    rows = [{"hash": "b1", "wos": ["wo-c", "wo-a"]}, {"hash": "b2", "wos": ["wo-b"]}]
    assert promoted_wos(rows, is_ancestor, "old", "new") == ["wo-c", "wo-a", "wo-b"]


def test_rows_already_in_old_are_skipped():
    rows = [{"hash": "a1", "wos": ["old-1"]}, {"hash": "b1", "wos": ["new-1"]}, {"hash": "a2", "wos": ["old-2"]}]
    assert promoted_wos(rows, is_ancestor, "old", "new") == ["new-1"]


def test_rows_with_no_hash_are_skipped():
    rows = [{"wos": ["no-key"]}, {"hash": "", "wos": ["empty"]}, {"hash": None, "wos": ["none"]},
            {"hash": "b2", "wos": ["kept"]}]
    assert promoted_wos(rows, is_ancestor, "old", "new") == ["kept"]


def test_rows_not_in_new_are_skipped():
    rows = [{"hash": "elsewhere", "wos": ["side"]}, {"hash": "b2", "wos": ["kept"]}]
    assert promoted_wos(rows, is_ancestor, "old", "new") == ["kept"]


def test_a_promoted_row_with_no_wos_adds_nothing():
    rows = [{"hash": "b1"}, {"hash": "b2", "wos": []}]
    assert promoted_wos(rows, is_ancestor, "old", "new") == []
