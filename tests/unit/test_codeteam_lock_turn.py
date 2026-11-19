"""The FIFO turn decision is pure; ticket values and expectations are literal."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_lock_turn import lock_turn


def test_oldest_live_ticket_is_head():
    assert lock_turn([(10, 1), (20, 2), (30, 3)], {1, 2, 3}) == ((10, 1), [])


def test_dead_tickets_are_skipped_and_returned_in_input_order():
    assert lock_turn([(30, 3), (5, 5), (20, 2), (10, 1)], {1, 3}) == (
        (10, 1), [(5, 5), (20, 2)]
    )


def test_equal_arrival_times_are_ordered_by_pid():
    assert lock_turn([(10, 8), (10, 2), (10, 5)], {2, 5, 8}) == ((10, 2), [])


def test_no_live_ticket_returns_none_and_all_dead_in_input_order():
    assert lock_turn([(30, 3), (10, 1), (20, 2)], {4}) == (
        None, [(30, 3), (10, 1), (20, 2)]
    )


def test_empty_tickets_return_none_and_no_dead():
    assert lock_turn([], {1}) == (None, [])


def test_unsorted_input_does_not_change_the_head():
    assert lock_turn([(30, 3), (10, 1), (20, 2)], {1, 2, 3}) == ((10, 1), [])
