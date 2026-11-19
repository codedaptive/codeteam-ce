#!/usr/bin/env python3
"""Ride choices for landing notices, with all external effects replaced."""
import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_ride_notices", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)

SYM = "own (A/own.rs:L1-L1)"


def queue_call(records, files, callers):
    team = SimpleNamespace(notify=Mock())
    rec = {"zone": "A", "wo": "change", "tree": "/change"}
    if callers is not ...:
        rec["interface_callers"] = callers
    with patch.object(cl, "interface_changes", return_value={SYM: ["B"]}), \
         patch.object(cl, "api_delta", return_value={}), patch.object(cl, "tag_wo"), \
         patch.object(cl, "open_records", return_value=[(Path("/record"), r) for r in records]), \
         patch.object(cl, "own_base", return_value="own-base") as base, \
         patch.object(cl, "changed_files", return_value=files) as changed:
        cl.queue_notices(team, rec, SimpleNamespace())
    team.notify.assert_called_once()
    args, kwargs = team.notify.call_args
    assert args[0:2] == ("Coord-B", "NOTE")
    assert "Interface change coming" in args[2]
    return kwargs, base, changed, team, rec


def test_interface_touching_open_order_wakes():
    kwargs, base, changed, team, _ = queue_call([{"zone": "B", "tree": "/b"}], ["B/caller.rs"],
                                                 {SYM: {"B": ["B/caller.rs"]}})
    assert kwargs.get("ride") is False
    base.assert_called_once_with(team, "/b")
    changed.assert_called_once_with("/b", "own-base")


def test_interface_unrelated_open_order_rides():
    kwargs, _, _, _, _ = queue_call([{"zone": "B", "tree": "/b"}], ["B/other.rs"],
                                     {SYM: {"B": ["B/caller.rs"]}})
    assert kwargs.get("ride") is True


def test_interface_without_open_orders_rides():
    kwargs, _, _, _, _ = queue_call([], [], {SYM: {"B": ["B/caller.rs"]}})
    assert kwargs.get("ride") is True


def test_interface_missing_callers_with_open_order_wakes():
    kwargs, _, changed, _, _ = queue_call([{"zone": "B", "tree": "/b"}], [], ...)
    assert kwargs.get("ride") is False
    changed.assert_not_called()


def test_interface_missing_symbol_with_open_order_wakes():
    kwargs, _, changed, _, _ = queue_call([{"zone": "B", "tree": "/b"}], [], {})
    assert kwargs.get("ride") is False
    changed.assert_not_called()


def test_interface_missing_zone_with_open_order_wakes():
    kwargs, _, changed, _, _ = queue_call([{"zone": "B", "tree": "/b"}], [], {SYM: {}})
    assert kwargs.get("ride") is False
    changed.assert_not_called()


def promotion_calls():
    team = SimpleNamespace(repo="/repo", notify=Mock(), m={"assistants": [{"role": "backporter", "name": "Backporter"}]},
                           c=Mock(return_value="Orchestrator"))
    with patch.object(cl, "out", return_value="A/own.rs\n"), \
         patch.object(cl, "ancestry", return_value=lambda a, b: b == "new"), \
         patch.object(cl, "read_landing_rows", return_value=[{"hash": "landed", "wos": ["w1"]}]), \
         patch.object(cl, "promotion_coordinators", return_value={"Coord-A": ["A"], "Orchestrator": ["orc"]}):
        cl.promoted_notices(team, "old", "new")
    return team.notify.call_args_list


def test_promotion_coordinator_notice_rides():
    calls = promotion_calls()
    notice = next(c for c in calls if c.args[0:2] == ("Coord-A", "NOTE"))
    assert "Promoted new" in notice.args[2]
    assert notice.kwargs.get("ride") is True


def test_promotion_orchestrator_notice_wakes():
    notice = next(c for c in promotion_calls() if c.args[0:2] == ("Orchestrator", "NOTE"))
    assert notice.kwargs.get("ride", False) is False


def test_promotion_pushed_messages_wake():
    pushed = [c for c in promotion_calls() if c.args[1] == "PUSHED"]
    assert {c.args[0] for c in pushed} == {"Orchestrator", "Backporter"}
    assert all(c.kwargs.get("ride", False) is False for c in pushed)


def test_markdown_broken_refs_notice_wakes():
    team = SimpleNamespace(repo="/repo", cfg={"docs": {"enabled": True}}, notify=Mock())
    rec = {"zone": "A", "wo": "w1"}
    with patch.object(cl, "out", return_value=""), patch.object(cl, "zone_docs", return_value=[]), \
         patch.object(cl, "tell_dependents"), patch.object(cl, "missing_file_refs", return_value=["missing.md"]), \
         patch.object(cl, "stated_levels", return_value=({}, None)):
        cl.docs_pass(team, {"hash": "new", "range": "old..new"}, rec)
    team.notify.assert_called_once()
    args, kwargs = team.notify.call_args
    assert args[0:2] == ("Coord-A", "NOTE")
    assert "landed with Markdown naming files that do not exist" in args[2]
    assert "missing.md" in args[2]
    assert kwargs.get("ride", False) is False


def test_cancel_own_work_notice_wakes_coordinator():
    team = SimpleNamespace(wo=Mock(return_value={"zone": "A", "queued": True}),
                           save_wo=Mock(), notify=Mock())
    entry = Mock()
    entry.read_text.return_value = '{"wos": ["w1"]}'
    with patch.object(cl, "Lock"), patch.object(cl, "entry_path", return_value=entry), \
         patch("builtins.print"):
        cl.cmd_land_cancel(team, SimpleNamespace(wo="w1", reason=""))
    team.notify.assert_called_once()
    call = team.notify.call_args
    assert call.args[0:2] == ("Coord-A", "NOTE")
    assert "taken out of the landing queue" in call.args[2]
    assert call.kwargs.get("ride", False) is False


def test_conflict_own_work_notice_wakes_coordinator():
    team = SimpleNamespace(dir=Path("/unused"), lab=False, save_wo=Mock(), notify=Mock(), log=Mock())
    rec = {"wo": "w1", "zone": "A", "queued": True}
    with patch.object(Path, "write_text"), patch.object(cl, "now", return_value="now"), \
         patch("builtins.print"):
        cl.landing_conflict(team, Mock(), [rec], ["A/file.py"], "w1", ["w0"])
    team.notify.assert_called_once()
    call = team.notify.call_args
    assert call.args[0:2] == ("Coord-A", "NOTE")
    assert "did not land" in call.args[2]
    assert call.kwargs.get("ride", False) is False


def test_review_findings_own_work_request_wakes_coordinator():
    team = SimpleNamespace(wo=Mock(return_value={"zone": "A", "queued": True}),
                           save_wo=Mock(), notify=Mock(), log=Mock())
    row = {"wo": "w1", "zone": "A"}
    findings = [{"id": "F1", "where": "A/file.py", "what": "fix this"}]
    with patch.object(cl, "entry_path", return_value=None), patch.object(cl, "now", return_value="now"):
        cl.send_review_back(team, row, findings, "Reviewer")
    team.notify.assert_called_once()
    call = team.notify.call_args
    assert call.args[0:2] == ("Coord-A", "REQUEST")
    assert "Stage 3 findings" in call.args[2]
    assert call.kwargs.get("ride", False) is False


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS {name}")
            except Exception as ex:
                failed += 1
                print(f"  FAIL {name}: {type(ex).__name__}: {ex}")
    print("all passed" if not failed else f"{failed} failed")
    sys.exit(1 if failed else 0)
