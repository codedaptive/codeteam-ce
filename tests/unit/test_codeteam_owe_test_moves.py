import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_owe_test_moves import owe_test_moves


def test_integration_move_adds_owed_file_and_sorted_zone():
    entry = {"zones": ["Z3", "Z4"], "other": "kept"}
    moves = [{"path": "tests/integration/test_a.py", "group": "integration"}]
    owe_test_moves(entry, moves, {"tests/integration/test_a.py": "Z2"}.__getitem__)
    assert entry == {"integration": "owed", "files": ["tests/integration/test_a.py"],
                     "zones": ["Z2", "Z3", "Z4"], "other": "kept"}


def test_owing_entry_appends_files_without_duplicate_files_or_zones():
    entry = {"integration": "owed", "files": ["a.py"], "zones": ["Z1"]}
    moves = [{"path": "tests/integration/test_b.py", "group": "integration"},
             {"path": "tests/integration/test_c.py", "group": "integration"},
             {"path": "tests/integration/test_b.py", "group": "integration"}]
    zones = {"tests/integration/test_b.py": "Z2", "tests/integration/test_c.py": "Z2"}
    owe_test_moves(entry, moves, zones.__getitem__)
    assert entry == {"integration": "owed", "files": ["a.py", "tests/integration/test_b.py",
                                                       "tests/integration/test_c.py"],
                     "zones": ["Z1", "Z2"]}


@pytest.mark.parametrize("group", ["validation", "unit"])
def test_non_integration_move_leaves_entry_exactly_unchanged(group):
    entry = {"integration": "passed", "files": ["old.py"], "zones": ["Z2", "Z1"], "extra": {"x": 1}}
    before = deepcopy(entry)
    owe_test_moves(entry, [{"path": "tests/test_a.py", "group": group}], {}.__getitem__)
    assert entry == before


def test_several_integration_moves_keep_file_order_and_sort_zones():
    entry = {}
    moves = [{"path": "tests/integration/test_z.py", "group": "integration"},
             {"path": "tests/integration/test_a.py", "group": "integration"},
             {"path": "tests/integration/test_m.py", "group": "integration"}]
    zones = {"tests/integration/test_z.py": "Z3", "tests/integration/test_a.py": "Z1",
             "tests/integration/test_m.py": "Z2"}
    owe_test_moves(entry, moves, zones.__getitem__)
    assert entry == {"integration": "owed", "files": ["tests/integration/test_z.py",
                                                       "tests/integration/test_a.py",
                                                       "tests/integration/test_m.py"],
                     "zones": ["Z1", "Z2", "Z3"]}
