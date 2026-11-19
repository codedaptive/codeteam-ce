#!/usr/bin/env -S python3 -u
"""A lane's current owns and the launch-environment fallback."""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "share" / "claude-hooks"))
from lane_own_owns import lane_own_owns  # noqa: E402

FALLBACK = [" /packages/libs/Old/ ", " / ", "", " docs/extra/ "]


def write_team(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def test_owns_list_is_normalized_and_stringified(path):
    write_team(path, {"lanes": {"AKit": {"owns": [" /packages/libs/New/ ", " / ", "", 42, True]}}})
    assert lane_own_owns(path, "AKit", FALLBACK) == ("packages/libs/New", "42", "True")


def test_null_owns_is_empty(path):
    write_team(path, {"lanes": {"AKit": {"owns": None}}})
    assert lane_own_owns(path, "AKit", FALLBACK) == ()


def test_empty_owns_is_empty(path):
    write_team(path, {"lanes": {"AKit": {"owns": []}}})
    assert lane_own_owns(path, "AKit", FALLBACK) == ()


def test_non_list_owns_uses_normalized_fallback(path):
    write_team(path, {"lanes": {"AKit": {"owns": "packages/libs/New"}}})
    assert lane_own_owns(path, "AKit", FALLBACK) == ("packages/libs/Old", "docs/extra")


def test_missing_owns_uses_fallback(path):
    write_team(path, {"lanes": {"AKit": {"path": "packages/kits/AKit"}}})
    assert lane_own_owns(path, "AKit", FALLBACK) == ("packages/libs/Old", "docs/extra")


def test_missing_lane_uses_fallback(path):
    write_team(path, {"lanes": {"BKit": {"owns": ["other"]}}})
    assert lane_own_owns(path, "AKit", FALLBACK) == ("packages/libs/Old", "docs/extra")


def test_non_object_lanes_uses_fallback(path):
    write_team(path, {"lanes": []})
    assert lane_own_owns(path, "AKit", FALLBACK) == ("packages/libs/Old", "docs/extra")


def test_missing_lanes_uses_fallback(path):
    write_team(path, {})
    assert lane_own_owns(path, "AKit", FALLBACK) == ("packages/libs/Old", "docs/extra")


def test_non_object_lane_uses_fallback(path):
    write_team(path, {"lanes": {"AKit": []}})
    assert lane_own_owns(path, "AKit", FALLBACK) == ("packages/libs/Old", "docs/extra")


def test_non_object_document_uses_fallback(path):
    write_team(path, [])
    assert lane_own_owns(path, "AKit", FALLBACK) == ("packages/libs/Old", "docs/extra")


def test_missing_file_uses_fallback(path):
    assert lane_own_owns(path, "AKit", FALLBACK) == ("packages/libs/Old", "docs/extra")


def test_unreadable_path_uses_fallback(path):
    path.mkdir()
    assert lane_own_owns(path, "AKit", FALLBACK) == ("packages/libs/Old", "docs/extra")


def test_invalid_json_uses_fallback(path):
    path.write_text("{not json", encoding="utf-8")
    assert lane_own_owns(path, "AKit", FALLBACK) == ("packages/libs/Old", "docs/extra")


def test_invalid_utf8_uses_fallback(path):
    path.write_bytes(b"\xff")
    assert lane_own_owns(path, "AKit", FALLBACK) == ("packages/libs/Old", "docs/extra")


def test_none_path_uses_fallback(path):
    assert lane_own_owns(None, "AKit", FALLBACK) == ("packages/libs/Old", "docs/extra")


def test_empty_fallback_returns_empty_tuple(path):
    assert lane_own_owns(path, "AKit", []) == ()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    fn(Path(tmp) / "team.json")
                except AssertionError:
                    print(f"FAIL {name}")
                    raise
            print(f"PASS {name}")
    print("all passed")
