import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_cwd_inside import cwd_inside


def test_equal_path_is_inside():
    assert cwd_inside("/t/wo/a", ["/t/wo/a"]) is True


def test_child_path_is_inside():
    assert cwd_inside("/t/wo/a", ["/t/wo/a/b"]) is True


def test_sibling_with_shared_prefix_is_not_inside():
    assert cwd_inside("/t/wo/a", ["/t/wo/ab"]) is False


def test_empty_cwds_are_not_inside():
    assert cwd_inside("/t/wo/a", []) is False


def test_one_matching_cwd_among_several_is_inside():
    assert cwd_inside("/t/wo/a", ["/t/wo/ab", "/other", "/t/wo/a/b"]) is True
