import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
import pytest

from codeteam_add_recheck_commit import add_recheck_commit


def test_appends_a_new_commit_to_the_named_finding_only():
    items = [{"id": "f#1", "Ms": ["old"]}, {"id": "f#2", "Ms": ["other"]}]
    assert add_recheck_commit(items, "f#2", "new") is True
    assert items == [{"id": "f#1", "Ms": ["old"]}, {"id": "f#2", "Ms": ["other", "new"]}]


def test_a_commit_already_there_changes_nothing():
    items = [{"id": "f#1", "Ms": ["old", "new"]}]
    assert add_recheck_commit(items, "f#1", "new") is False
    assert items == [{"id": "f#1", "Ms": ["old", "new"]}]


def test_an_unknown_id_raises():
    with pytest.raises(StopIteration):
        add_recheck_commit([{"id": "f#1", "Ms": []}], "f#9", "new")
