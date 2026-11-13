"""lane_work: in a v5 team, a ledger row whose stage starts with blocked, waits, waiting, held, handed or accepted is
waiting, not work, and so is a row whose work order the landing tool holds.

2026-11-12: one lane's only row, 'plugin-docs-raw-scan · blocked-guard', waited for the owner's walls
decision; its untouched tree made it a DEAD LEAD, and so IDLE WITH WORK, every patrol round. In v5 nothing clears such
a wait by itself (there is no push-up await); what ends it reaches the lane as mail and the lane stages the row again.
A v1 team keeps the await rule (tests/run.sh): a stage word alone silences nothing there.

2026-11-12: two finished work orders were DEAD LEAD every round: tooling's 'handed-back' member of a
--with set not yet queued, and an app's 'set-bounced-corekit-conflict-orc-requeues', whose set Stage 4 sent back on a
conflict to wait for a promote. The landing tool's record says which work orders it holds (queued, held, landed,
retired, or bounced with nothing done in the tree since); a lead resuming in a bounced tree is judged again.
"""

import importlib.machinery
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def codeteam():
    environment = os.environ.copy()
    dont_write_bytecode = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        if "herdr" in os.environ.get("SSH_AUTH_SOCK", ""):
            os.environ.pop("SSH_AUTH_SOCK")
        for name in list(os.environ):
            if name.startswith("CT_"):
                os.environ.pop(name)
        loader = importlib.machinery.SourceFileLoader("codeteam_lane_work", str(ROOT / "bin" / "codeteam"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = dont_write_bytecode
        os.environ.clear()
        os.environ.update(environment)


def judge(codeteam, monkeypatch, tmp_path, rows, *, v5, records=None, bounce_age_h=None):
    """lane_work over these ledger rows, each with one lead tree (agent-w) untouched for two hours and nobody inside
    it. records: land/wo file name -> JSON body for agent-w; bounce_age_h: hours since agent-w.bounce.txt was written."""
    (tmp_path / ".ledger.md").write_text("".join(f"{n} · {s} · agent-x\n" for n, s in rows))
    now = time.time()
    wo_dir = tmp_path / "team" / "land" / "wo"
    wo_dir.mkdir(parents=True)
    for name, body in (records or {}).items():
        (wo_dir / name).write_text(json.dumps(body))
    if bounce_age_h is not None:
        b = wo_dir / "agent-w.bounce.txt"
        b.write_text("agent-w did not land: the set was sent back\n")
        os.utime(b, (now - bounce_age_h * 3600, now - bounce_age_h * 3600))
    monkeypatch.setattr(codeteam, "lane_ledger_dir", lambda t, n, r: tmp_path)
    monkeypatch.setattr(codeteam, "awaited", lambda t, n: set())
    monkeypatch.setattr(codeteam, "_lead_paths", lambda t, n, ids: [tmp_path / "agent-w"])
    monkeypatch.setattr(codeteam, "_last_activity", lambda p: now - 2 * 3600)
    monkeypatch.setattr(codeteam, "_someone_inside", lambda p: False)
    t = SimpleNamespace(m={"land": {"enabled": True}} if v5 else {}, root=tmp_path / "team")
    _, active, dead, parked, queued = codeteam.lane_work(t, "lane", {}, now)
    return active, dead, parked, queued


@pytest.mark.parametrize("stage", ["blocked-guard", "blocked", "waits-promote", "waiting-owner-scope",
                                   "held-until-first-promote", "Blocked: walls", "handed-back", "Handed back to Orc",
                                   "accepted"])
def test_v5_waiting_row_is_not_work(codeteam, monkeypatch, tmp_path, stage):
    assert judge(codeteam, monkeypatch, tmp_path, [("r", stage)], v5=True) == ([], [], 0, [])


@pytest.mark.parametrize("stage", ["lead-started", "review", "reported-Fable-held-question", "blockedx", "unblocked",
                                   "handedness", "set-bounced-corekit-conflict-orc-requeues"])
def test_v5_other_rows_are_still_judged_by_their_tree(codeteam, monkeypatch, tmp_path, stage):
    assert judge(codeteam, monkeypatch, tmp_path, [("r", stage)], v5=True) == ([], ["r"], 0, [])


def test_v1_keeps_the_await_rule(codeteam, monkeypatch, tmp_path):
    assert judge(codeteam, monkeypatch, tmp_path, [("r", "blocked-guard")], v5=False) == ([], ["r"], 0, [])


def test_v5_queued_rows_still_count(codeteam, monkeypatch, tmp_path):
    rows = [("b", "blocked-guard"), ("q", "queued")]
    assert judge(codeteam, monkeypatch, tmp_path, rows, v5=True) == ([], [], 0, ["q"])


OPEN = {"wo": "agent-w", "zone": "lane", "tree": "agent-w"}


@pytest.mark.parametrize("records, bounce_age_h", [
    ({"agent-w.json": {**OPEN, "queued": "2026-11-12T10:00:00-06:00"}}, None),
    ({"agent-w.json": {**OPEN, "held": {"because": "waits for the owner", "at": "2026-11-12T10:00:00-06:00"}}}, None),
    ({"agent-w.json": OPEN, "agent-w.landed.json": {**OPEN, "tip": "abc"}}, None),
    ({"agent-w.retired.json": {**OPEN, "tip": "abc"}}, None),
    ({"agent-w.json": {**OPEN, "set": ["agent-v", "agent-w"]}}, 1),     # sent back after the tree last moved
])
def test_v5_a_work_order_the_landing_tool_holds_is_not_a_dead_lead(codeteam, monkeypatch, tmp_path, records,
                                                                     bounce_age_h):
    stage = "set-bounced-corekit-conflict-orc-requeues"
    assert judge(codeteam, monkeypatch, tmp_path, [("r", stage)], v5=True, records=records,
                 bounce_age_h=bounce_age_h) == ([], [], 0, [])


@pytest.mark.parametrize("records, bounce_age_h", [
    ({"agent-w.json": OPEN}, None),                                      # open, never queued: judged by its tree
    ({"agent-w.json": {**OPEN, "set": ["agent-v", "agent-w"]}}, 3),     # a lead worked in the tree after the bounce
    ({}, 1),                                                             # a bounce file with no record of the work order
])
def test_v5_an_open_work_order_is_still_judged_by_its_tree(codeteam, monkeypatch, tmp_path, records, bounce_age_h):
    stage = "set-bounced-corekit-conflict-orc-requeues"
    assert judge(codeteam, monkeypatch, tmp_path, [("r", stage)], v5=True, records=records,
                 bounce_age_h=bounce_age_h) == ([], ["r"], 0, [])


def test_v1_ignores_the_landing_records(codeteam, monkeypatch, tmp_path):
    records = {"agent-w.json": {**OPEN, "queued": "2026-11-12T10:00:00-06:00"}}
    assert judge(codeteam, monkeypatch, tmp_path, [("r", "lead-started")], v5=False, records=records) == ([], ["r"], 0, [])
