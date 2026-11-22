#!/usr/bin/env -S python3 -u
"""A --with set's Stage 3 request tells the reviewer which members land with each one, and their tips, so a docs member
describing a code member is judged at the set's tip, not at landing (2026-11-12: a docs
work order bounced twice because its claims about sync's code were false at landing)."""
import importlib.machinery
import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_stage3_set", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)


class FakeTeam:
    def __init__(self, d):
        self.dir = Path(d)
        self.repo = Path(d) / "repo"
        self.manifest = Path(d) / "t.toml"
        self.landing = "landing"
        for sub in ("wo", "reviews", "queue"):
            (self.dir / sub).mkdir()

    def c(self, key, default):
        return "OrchestratorName" if key == "orchestrator" else default

    wo_file = cl.Team.wo_file
    save_wo = cl.Team.save_wo


def row(rec):
    return {"stage": 3, "wo": rec["wo"], "zone": rec["zone"], "feature": rec["wo"], "tip": rec["tip"],
            "reviewers": {"Kong": "pending"}, "commits": {}, "seen": {}, "requested": "t", "state": "pending"}


def recs():
    return [{"wo": "agent-sync", "zone": "sync", "tip": "35c979dc" + "0" * 32},
            {"wo": "docs-sync", "zone": "orc", "tip": "db598cab" + "0" * 32}]


def test_a_set_member_names_the_others_and_their_tips():
    with tempfile.TemporaryDirectory() as d:
        team = FakeTeam(d)
        with patch.object(cl, "stage3_record", side_effect=lambda t, rec, **kw: row(rec)), \
                patch.object(cl, "landed_refs", return_value=["refs/heads/landing", "refs/heads/integration"]):
            requests = cl.queue_stage3(team, recs(), {"wo": "agent-sync"}, "now")
            text = cl.stage3_request(team, requests["Kong"])
        docs = next(r for r in requests["Kong"] if r["wo"] == "docs-sync")
        assert docs["with"] == [{"wo": "agent-sync", "zone": "sync", "tip": "35c979dc" + "0" * 32}], docs["with"]
        saved = json.loads((team.dir / "reviews" / "docs-sync.json").read_text())
        assert saved["with"][0]["wo"] == "agent-sync"
        assert "It lands in one step with agent-sync (zone sync, tip 35c979dc00)" in text, text
        assert "judge what it says about their code at their tips, not at landing" in text
        whole = f"log -p --remerge-diff {'db598cab' + '0' * 32} {'35c979dc' + '0' * 32} --not refs/heads/landing"
        assert whole in text, text


def test_a_set_request_says_a_finding_may_name_any_member():
    # Kong read a passed member wrong with the set and had no way to record it before landing.
    with tempfile.TemporaryDirectory() as d:
        team = FakeTeam(d)
        with patch.object(cl, "stage3_record", side_effect=lambda t, rec, **kw: row(rec)), \
                patch.object(cl, "landed_refs", return_value=["refs/heads/landing"]):
            text = cl.stage3_request(team, cl.queue_stage3(team, recs(), {"wo": "agent-sync"}, "now")["Kong"])
        assert "A finding may name any member of the set, with that member's --wo and --zone" in text, text
        assert "`reviewed docs-sync` then sends the whole set back" in text, text
        assert "holds its verdict already and takes no `reviewed`" in text, text


def test_a_lone_work_order_gets_no_set_line():
    with tempfile.TemporaryDirectory() as d:
        team = FakeTeam(d)
        with patch.object(cl, "stage3_record", side_effect=lambda t, rec, **kw: row(rec)), \
                patch.object(cl, "landed_refs", return_value=["refs/heads/landing"]):
            requests = cl.queue_stage3(team, recs()[:1], {"wo": "agent-sync"}, "now")
            text = cl.stage3_request(team, requests["Kong"])
        assert "with" not in requests["Kong"][0]
        assert "lands in one step" not in text


def test_the_request_says_to_judge_own_changes_never_a_two_dot_diff_against_landing():
    # A docs work order bounced for "reverting" sync.md, which landed after its tree's last merge.
    with tempfile.TemporaryDirectory() as d:
        team = FakeTeam(d)
        with patch.object(cl, "stage3_record", side_effect=lambda t, rec, **kw: row(rec)), \
                patch.object(cl, "landed_refs", return_value=["refs/heads/landing"]):
            text = cl.stage3_request(team, cl.queue_stage3(team, recs()[:1], {"wo": "agent-sync"}, "now")["Kong"])
        assert "`git diff landing...<tip>` (from its merge base)" in text, text
        assert "never a two-dot diff of the tip against landing" in text, text


def test_review_questions_go_to_the_named_orchestrator_not_a_reply():
    with tempfile.TemporaryDirectory() as d:
        team = FakeTeam(d)
        with patch.object(cl, "stage3_record", side_effect=lambda t, rec, **kw: row(rec)), \
                patch.object(cl, "landed_refs", return_value=["refs/heads/landing"]):
            text = cl.stage3_request(team, cl.queue_stage3(team, recs()[:1], {"wo": "agent-sync"}, "now")["Kong"])
        assert "OrchestratorName" in text, text
        assert "REQUEST" in text, text
        assert any(phrase in text.lower() for phrase in ("reads no reply", "no reply is read", "no reply will be read")), text
        assert "work order" in text.lower(), text


if __name__ == "__main__":
    import sys
    failed = 0
    for name, test in list(globals().items()):
        if name.startswith("test_") and callable(test):
            try:
                test()
                print(f"  PASS {name}")
            except Exception as exc:
                failed += 1
                print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"{failed} failed" if failed else "all passed")
    sys.exit(bool(failed))
