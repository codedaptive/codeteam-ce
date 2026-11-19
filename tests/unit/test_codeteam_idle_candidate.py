import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_idle_candidate import idle_candidate


def test_idle_tree_with_only_codegraph_is_candidate():
    assert idle_candidate(100.0, 201.0, 100.0, True, None, False, False) is True


def test_idle_tree_with_build_folder_is_candidate():
    assert idle_candidate(100.0, 201.0, 100.0, True, "", False, False) is True


def test_recent_tree_is_not_candidate():
    assert idle_candidate(100.0, 200.0, 100.0, True, None, False, False) is False


def test_idle_tree_without_cleanable_folders_is_not_candidate():
    assert idle_candidate(100.0, 201.0, 100.0, False, None, False, False) is False


def test_cleaned_tree_used_after_mark_is_candidate():
    assert idle_candidate(3601.0, 7202.0, 3600.0, True, "1970-01-01T01:00:00+00:00", False, False) is True


def test_cleaned_tree_not_used_after_mark_is_not_candidate():
    assert idle_candidate(3599.0, 7202.0, 3600.0, True, "1970-01-01T01:00:00+00:00", False, False) is False


def test_mark_with_utc_offset_is_compared_as_an_instant():
    assert idle_candidate(3601.0, 7202.0, 3600.0, True, "1970-01-01T02:00:00+01:00", False, False) is True
    assert idle_candidate(3599.0, 7202.0, 3600.0, True, "1970-01-01T02:00:00+01:00", False, False) is False


def test_59_minutes_is_not_idle_at_one_hour():
    assert idle_candidate(0, 3540, 3600, True, None, False, False) is False


def test_61_minutes_is_idle_at_one_hour():
    assert idle_candidate(0, 3660, 3600, True, None, False, False) is True


def test_inside_idle_tree_is_not_candidate():
    assert idle_candidate(0, 3660, 3600, True, None, True, False) is False


def test_landed_tree_without_mark_is_candidate_even_if_fresh():
    assert idle_candidate(100, 100, 3600, True, None, False, True) is True


def test_landed_tree_with_mark_is_not_candidate():
    assert idle_candidate(0, 3660, 3600, True, "1970-01-01T00:00:00+00:00", False, True) is False


def test_landed_tree_without_cleanable_folders_is_not_candidate():
    assert idle_candidate(0, 3660, 3600, False, None, False, True) is False


def test_landed_tree_with_someone_inside_is_not_candidate():
    assert idle_candidate(0, 3660, 3600, True, None, True, True) is False
