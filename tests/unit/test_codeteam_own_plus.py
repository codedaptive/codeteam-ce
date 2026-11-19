import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_own_plus import own_plus


def test_none_keeps_plus_unchanged():
    assert own_plus({"A/a": {1, 2}, "B/b": {3}}, None) == {"A/a": {1, 2}, "B/b": {3}}


def test_intersects_own_lines_and_keeps_all_plus_paths():
    assert own_plus({"A/a": {1, 2}, "B/b": {3}, "C/c": {4}},
                    {"A/a": {2, 9}, "B/b": {8}, "D/d": {5}}) == {
                        "A/a": {2}, "B/b": set(), "C/c": set()}
