#!/usr/bin/env -S python3 -u
"""A test belongs to the longest matching owned entry."""
import fnmatch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_owning_zone import owning_zone


def in_scope(path, entry):
    return entry in ("", ".") or path == entry or path.startswith(entry + "/") or fnmatch.fnmatchcase(path, entry)


def test_longest_and_glob_owner():
    zones = {"whole": ["."], "tests": ["tests"], "pipeline": ["tests/unit/land-*.py"]}
    assert owning_zone(zones, "tests/unit/land-a.py", in_scope) == "pipeline"


def test_first_wins_ties():
    assert owning_zone({"first": ["tests"], "second": ["tests"]}, "tests/a.py", in_scope) == "first"


def test_dot_and_empty_count_zero():
    assert owning_zone({"first": [""], "second": ["."]}, "x", in_scope) == "first"
    assert owning_zone({"first": ["."], "second": ["x"]}, "x/a", in_scope) == "second"


def test_no_owner():
    assert owning_zone({"a": ["a"]}, "b/x", in_scope) is None


failed = 0
for name, test in list(globals().items()):
    if name.startswith("test_") and callable(test):
        try:
            test()
            print(f"PASS {name}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
print(f"{failed} failed" if failed else "all passed")
sys.exit(bool(failed))
