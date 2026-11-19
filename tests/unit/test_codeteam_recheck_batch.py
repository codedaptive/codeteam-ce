import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_recheck_batch import recheck_batch


def test_done_rows_are_skipped_and_equal_commits_do_not_call_contains():
    calls = []
    rows = [{"M": "old", "done": "t"}, {"M": "new"}, {"M": "new"}]
    assert recheck_batch(rows, lambda newest, old: calls.append((newest, old))) == [1, 2]
    assert calls == []


def test_all_ancestor_rows_join_in_file_order():
    calls = []
    def contains(newest, old):
        calls.append((newest, old))
        return True
    assert recheck_batch([{"M": "a"}, {"M": "b"}, {"M": "c"}], contains) == [0, 1, 2]
    assert all(newest == "c" and newest != old for newest, old in calls)


def test_unrelated_commit_waits():
    rows = [{"M": "a"}, {"M": "unrelated"}, {"M": "c"}]
    assert recheck_batch(rows, lambda newest, old: (newest, old) == ("c", "a")) == [0, 2]


def test_pending_move_precedes_non_move():
    rows = [{"M": "a"}, {"M": "b", "move": True}, {"M": "c", "move": True}]
    assert recheck_batch(rows, lambda *_: False) == [1]


def test_nothing_pending():
    assert recheck_batch([{"done": "t", "move": True}], lambda *_: False) == []
    assert recheck_batch([], lambda *_: False) == []
