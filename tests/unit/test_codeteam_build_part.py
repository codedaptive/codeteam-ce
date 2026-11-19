import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))


@pytest.mark.parametrize(("record", "expected"), [
    ({"build_seconds": 160.4}, ", build 160 s"),
    ({"build_seconds": 0}, ", build 0 s"),
    ({"build_seconds": 12.6}, ", build 13 s"),
])
def test_numeric_build_seconds_are_formatted(record, expected):
    from codeteam_build_part import build_part

    assert build_part(record) == expected


@pytest.mark.parametrize("record", [
    {}, None, "not a dict", [], {"other": 3}, {"build_seconds": True},
    {"build_seconds": False}, {"build_seconds": "160"}, {"build_seconds": None},
])
def test_absent_or_nonnumeric_build_seconds_are_omitted(record):
    from codeteam_build_part import build_part

    assert build_part(record) == ""
