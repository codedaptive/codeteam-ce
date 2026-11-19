#!/usr/bin/env -S python3 -u
"""Stage 3 and the security-findings rule (2026-11-17): a security finding, whoever files it, never sends a work
order back, never refuses its next land and is not closed by the work order landing; it goes to the orchestrator at
once as a fix-forward for the owning zone. Other kinds hold as before. Git, findings and messages are faked; nothing
touches a repo."""
import importlib.machinery
import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_security", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", stderr="", returncode=0)):
    loader.exec_module(cl)

TIP = "t" * 40
REC = {"wo": "w1", "tip": TIP}
PREVIOUS = {"reviewers": {"Kong": "findings"}, "seen": {"Kong": [TIP]}}


def finding(kind, state="open", by="Kong", wo="w1", fid="f#1", time="2026-11-17T12:00:00"):
    return {"id": fid, "kind": kind, "state": state, "by": by, "also": [], "wos": [wo], "time": time,
            "zone": "cli", "where": "a.py:1", "what": "x"}


def test_an_open_security_finding_does_not_refuse_the_next_land():
    with patch.object(cl, "review_range", return_value=[]), \
            patch.object(cl, "all_findings", return_value=[finding("security")]):
        assert cl.reviewer_ranges(SimpleNamespace(), REC, PREVIOUS, ["Kong"]) == {}


def test_an_open_spec_finding_beside_it_still_refuses():
    with patch.object(cl, "review_range", return_value=[]), \
            patch.object(cl, "all_findings", return_value=[finding("security"), finding("spec", fid="f#2")]):
        try:
            cl.reviewer_ranges(SimpleNamespace(), REC, PREVIOUS, ["Kong"])
        except SystemExit:
            return
    raise AssertionError("not refused")


def test_open_holding_findings_leave_out_security_dropped_and_other_work_orders():
    items = [finding("security"), finding("spec", state="dropped", fid="f#2"), finding("layer", wo="w2", fid="f#3"),
             finding("test", fid="f#4")]
    with patch.object(cl, "all_findings", return_value=items):
        assert [f["id"] for f in cl.open_holding_findings(SimpleNamespace(), "w1")] == ["f#4"]


def verdict(findings):
    """Kong's verdict on w1 with these findings filed during its review: (row, sent back, closed finding ids)."""
    row = {"wo": "w1", "zone": "cli", "tip": TIP, "requested": "2026-11-17T11:00:00", "state": "pending",
           "reviewers": {"Kong": "pending"}, "seen": {}}
    sent, closed = [], []
    with patch.object(cl, "all_findings", return_value=findings), \
            patch.object(cl, "save_record", lambda path, r: None), \
            patch.object(cl, "send_review_back", lambda team, r, found, reviewer, via=None: sent.extend(found)), \
            patch.object(cl, "update_finding", lambda team, fid, **kw: closed.append(fid)), \
            patch.object(cl, "release_reviewed_entry", lambda team, wo: None), \
            patch.object(cl, "review_entry_notice", lambda team, wo: "notice"):
        cl.stage3_verdict(SimpleNamespace(), Path("/nonexistent"), row, "Kong")
    return row, sent, closed


def test_a_security_finding_alone_lets_the_work_order_land_and_stays_open():
    row, sent, closed = verdict([finding("security")])
    assert row["state"] == "land"
    assert row["reviewers"]["Kong"] == "pass"
    assert sent == []
    assert closed == []                     # open until its fix-forward lands with --fixes


def test_a_spec_finding_still_sends_the_work_order_back():
    row, sent, closed = verdict([finding("security"), finding("spec", fid="f#2")])
    assert row["state"] == "findings"
    assert [f["id"] for f in sent] == ["f#2"]


def test_a_finding_waits_for_the_verdict_unless_it_is_a_security_finding():
    pending = {"w1": {}, "w2": {}}
    assert cl.held_for_verdict(["w1", "w2"], pending, finding("spec")) is True
    assert cl.held_for_verdict(["w1"], pending, finding("security")) is False
    assert cl.held_for_verdict(["w1", "w3"], pending, finding("spec")) is False      # w3 is not under review
    assert cl.held_for_verdict([], pending, finding("spec")) is False


def notified(me, kind, zone="cli"):
    sent = []
    team = SimpleNamespace(m={}, manifest="/m/team.toml", c=lambda key, default=None: default,
                           notify=lambda to, typ, text: sent.append((to, typ, text)))
    a = SimpleNamespace(zone=zone, wo=["w1"], severity=2, kind=kind, where="a.py:1", what="x", belongs="")
    cl.notify_finding(team, a, "feat#1", me)
    return sent


def test_kongs_security_finding_is_raised_to_the_orchestrator():
    [(to, typ, text)] = notified("Kong", "security")
    assert (to, typ) == ("orc", "REQUEST")
    assert "holds nothing" in text
    assert "Route to Coord-cli as a fix-forward work order" in text


def test_kongs_other_findings_still_go_to_the_zone():
    [(to, _, text)] = notified("Kong", "spec")
    assert to == "Coord-cli"
    assert "the security-findings rule" not in text


if __name__ == "__main__":
    import inspect
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn()
                print(f"  PASS {name}")
            except Exception as ex:          # report every case, then fail once
                failed += 1
                print(f"  FAIL {name}: {type(ex).__name__}: {ex}")
    print("all passed" if not failed else f"{failed} failed")
    raise SystemExit(1 if failed else 0)
