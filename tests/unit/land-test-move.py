#!/usr/bin/env python3
"""Stage 2 test-move wiring, with the landing dependencies faked."""
import contextlib
import importlib.machinery
import importlib.util
import io
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_test_move", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch("subprocess.run", return_value=SimpleNamespace(stdout="", stderr="", returncode=0)):
    loader.exec_module(cl)

INTEGRATION = "test-move: no build; the moved tests run in the integration step"
VALIDATION = "test-move: no build; the moved tests run at Stage 6"


def move(group):
    path = f"A/tests/{group}/test_x.py"
    return {"path": path, "from": "A/tests/unit/test_x.py", "to": path, "group": group}


def record(wo, group):
    return {"wo": wo, "zone": "A", "tree": "/fake", "moved_tests": [move(group)]}


def stamp(members):
    with patch.object(cl, "queue_notices"):
        return cl.stamp_members(Mock(), SimpleNamespace(), members, [r["wo"] for r, _ in members], [], [], None, 0)


def test_integration_label_for_mixed_move_groups():
    a, b = record("a", "validation"), record("b", "integration")
    assert stamp([(a, "test-move"), (b, "test-move")]) == INTEGRATION
    assert a["no_build"] == VALIDATION
    assert b["no_build"] == INTEGRATION


def test_validation_only_label():
    a = record("a", "validation")
    assert stamp([(a, "test-move")]) == VALIDATION
    assert a["no_build"] == VALIDATION


def test_comment_and_move_set_label():
    a, b = {"wo": "a"}, record("b", "integration")
    assert stamp([(a, "comment-only"), (b, "test-move")]) == INTEGRATION


def test_building_member_suppresses_label():
    a, b = {"wo": "a", "no_build": "stale"}, record("b", "integration")
    assert not stamp([(a, None), (b, "test-move")])
    assert "no_build" not in a and "no_build" not in b


def test_checked_members_drops_stale_moves():
    rec = record("a", "integration")
    team = Mock(m={})
    team.wo.return_value = rec
    with contextlib.ExitStack() as stack:
        for name, value in {"_refuse_unlandable_set": None, "put_back_set_merge": None,
                            "carried_check": None, "check_work_order": [], "no_build_kind": "docs-only"}.items():
            stack.enter_context(patch.object(cl, name, return_value=value))
        cl.checked_members(team, ["a"])
    assert "moved_tests" not in rec


def queue(group, owner):
    rec = record("a", group)
    team = Mock(repo=Path("/fake"), integration="integration", zones={})
    saved = []
    with contextlib.ExitStack() as stack:
        replacements = {"checked_members": [(rec, "test-move")], "out": "tip", "merge_checked_base": None,
                        "changed_files": [move(group)["path"]], "own_base": "base",
                        "check_combined_members": ([], []), "slow_tests_flag": None, "now": "now",
                        "test_run_s": 0, "queue_notices": None, "owning_zone": owner,
                        "queue_stage3": {}, "report_slow_tests": None}
        for name, value in replacements.items():
            stack.enter_context(patch.object(cl, name, return_value=value))
        stack.enter_context(patch.object(cl, "Lock", return_value=contextlib.nullcontext()))
        stack.enter_context(patch.object(cl, "queue_stage3", side_effect=lambda team, recs, entry, queued: saved.append(entry) or {}))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            cl.check_and_queue(team, SimpleNamespace(wo="a"), ["a"])
    return saved[0], output.getvalue()


def test_integration_move_owes_owned_zone_and_output_label():
    entry, output = queue("integration", "B")
    assert entry.get("integration") == "owed"
    assert entry["files"] == ["A/tests/integration/test_x.py"]
    assert entry["zones"] == ["B"]
    assert f"Stage 2 passed ({INTEGRATION})" in output


def test_integration_move_falls_back_to_member_zone():
    entry, _ = queue("integration", None)
    assert entry.get("integration") == "owed"
    assert entry["zones"] == ["A"]


def test_validation_move_owes_nothing():
    entry, output = queue("validation", None)
    assert "integration" not in entry
    assert entry["zones"] == []
    assert f"Stage 2 passed ({VALIDATION})" in output


def test_stage3_request_explains_misfiled_tests():
    team = SimpleNamespace(repo=Path("/fake"), landing="landing", manifest="team.toml")
    with patch.object(cl, "landed_refs", return_value=[]):
        text = cl.stage3_request(team, []).lower()
    assert "wrong group" in text and "unit" in text and "finding" in text and "doc-fix" in text
    assert "is moved with doc-fix" in text
    assert "a move into unit is filed as a finding" in text


if __name__ == "__main__":
    failures = 0
    for name, test in list(globals().items()):
        if name.startswith("test_") and callable(test):
            try:
                test()
                print(f"PASS {name}")
            except Exception:
                failures += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    print(f"{failures} failed")
    sys.exit(bool(failures))
