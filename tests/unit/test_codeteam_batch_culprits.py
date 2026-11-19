import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_batch_culprits import batch_culprits


def test_ranges_are_inclusive_and_exclude_outside_lines():
    changes = {"entry": {"a.py": [(10, 12)]}}
    assert batch_culprits([["a.py", 9], ["a.py", 10], ["a.py", 12], ["a.py", 13]], changes) == {
        "entry": [["a.py", 10], ["a.py", 12]]}


def test_unknown_line_matches_changed_file():
    assert batch_culprits([["a.py", None], ["b.py", None]], {"one": {"a.py": [(2, 3)]}}) == {
        "one": [["a.py", None]]}


def test_shared_file_matches_both_entries_at_file_level():
    assert batch_culprits([["shared.py", 99]], {
        "a": {"shared.py": [(1, 2)]}, "b": {"shared.py": [(4, 5)]}}) == {
        "a": [["shared.py", 99]], "b": [["shared.py", 99]]}


def test_empty_ranges_match_any_line():
    assert batch_culprits([["removed.py", 100]], {"one": {"removed.py": []}}) == {
        "one": [["removed.py", 100]]}


def test_entries_and_frames_keep_input_order():
    frames = [["b.py", 4], ["a.py", 1], ["b.py", 2]]
    changes = {"second": {"a.py": [(1, 1)], "b.py": [(2, 4)]}, "first": {"c.py": [(1, 1)]}}
    assert batch_culprits(frames, changes) == {"second": [["b.py", 4], ["a.py", 1], ["b.py", 2]]}
