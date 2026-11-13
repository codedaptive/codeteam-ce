#!/usr/bin/env -S python3 -u
"""Isolated Stage 3 review, feature-round and finding contracts."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_review", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)


def make_team(root):
    repo = root / "repo"
    repo.mkdir()
    manifest = root / "sample.toml"
    manifest.write_text(f'repo = "{repo}"\nworktree_root = "{root / "team"}"\n'
                        '[[lanes]]\nname = "A"\npath = "A"\n'
                        '[[assistants]]\nname = "Perkins"\n'
                        '[[assistants]]\nname = "Nagatha"\n'
                        '[land]\norchestrator = "Skippy"\n')
    team = cl.Team(str(manifest))
    team.notify = Mock()
    return team



def review(team, wo):
    return json.loads((team.dir / "reviews" / f"{wo}.json").read_text())


def save_review(team, wo, state="pending"):
    row = {"stage": 3, "wo": wo, "zone": "A", "feature": "feat", "tip": "tip-" + wo,
           "reviewers": {"Kong": "pending"}, "commits": {"Kong": ["tip-" + wo]}, "seen": {},
           "requested": "2026-11-10T12:00:00+00:00", "state": state}
    (team.dir / "reviews" / f"{wo}.json").write_text(json.dumps(row))
    return row


def queue(team, wo):
    rec = {"wo": wo, "zone": "A", "tree": wo, "branch": "wo/A/" + wo}
    team.save_wo(rec)
    def out(repo, *args):
        if args[0] == "rev-parse": return "base" if repo == team.repo else "tip-" + str(repo)
        if args[0] == "rev-list": return args[2]
        if args[0] == "diff-tree": return "A/value"
        return "own change"
    with patch.object(cl, "checked_members", return_value=[(rec, True)]), patch.object(cl, "merge_checked_base"), \
            patch.object(cl, "changed_files", return_value=["A/value"]), \
            patch.object(cl, "check_combined_members", return_value=(["A"], ["A"])), \
            patch.object(cl, "queue_notices"), patch.object(cl, "out", side_effect=out):
        cl.check_and_queue(team, SimpleNamespace(wo=wo), [wo])
    return cl.entry_path(team, wo)


def call_reviewed(team, wo):
    with patch.object(cl, "Team", return_value=team), patch.dict(os.environ, CODETEAM_SESSION="Kong"):
        cl.main([str(team.manifest), "reviewed", wo])


def test_reviews_of_separate_entries_do_not_wait():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        one, two = queue(team, "one"), queue(team, "two")
        assert [json.loads(p.read_text())["review"] for p in (one, two)] == ["pending", "pending"]
        assert [call.args[:2] for call in team.notify.call_args_list] == [("Kong", "REQUEST"), ("Kong", "REQUEST")]
        call_reviewed(team, "two")
        assert json.loads(one.read_text())["review"] == "pending"
        assert json.loads(two.read_text())["review"] == "land"


def test_own_changes_and_request_text():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        row = {"wo": "w1", "zone": "A", "feature": "feat", "tip": "TIP", "recipient": "Kong", "seen": {"Kong": ["SEEN"]}}
        text = cl.stage3_request(team, [row])
        assert f"git -C {team.repo} log --no-merges -p TIP --not refs/heads/landing refs/heads/integration SEEN" in text
        assert f"codeteam-land {team.manifest} reviewed w1" in text
        assert "finding <feature> --wo <wo>" in text
        assert "Stage 3 review before landing" in text
        assert "run `reviewed` for each work order in every case: with findings filed it sends them" in text


def test_after_landing_records_feature_rounds_without_guard_handoff():
    team = SimpleNamespace(cfg={"review_after": {"enabled": True}})
    record = {"wo": "api", "zone": "A", "landed_commit": "landed-hash"}
    with patch.object(cl, "load_feature", return_value={"feature": "api", "landed": []}), \
            patch.object(cl, "save_feature") as save, patch.object(cl, "features_due") as due, \
            patch.object(cl, "now", return_value="landed-time"):
        cl.after_landing(team, [record])
    assert save.call_args.args[1]["landed"] == [{"wo": "api", "zone": "A", "hash": "landed-hash", "time": "landed-time", "review": "before"}]
    due.assert_called_once_with(team)


def test_after_landing_with_feature_rounds_disabled_sends_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp)); team.cfg["review_after"] = {"enabled": False}
        cl.after_landing(team, [{"wo": "w1", "zone": "A", "landed_commit": "M"}])
        assert list((team.dir / "reviews").glob("*.json")) == []
        team.notify.assert_not_called()


def test_kong_review_records_clean_verdict_on_tip():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp)); queue(team, "w1")
        call_reviewed(team, "w1")
        row = review(team, "w1")
        assert (row["state"], row["reviewers"], row["seen"]) == ("land", {"Kong": "pass"}, {"Kong": ["tip-w1"]})


def test_kong_review_counts_current_guard_findings_but_not_dropped():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp)); queue(team, "w1")
        r = review(team, "w1"); r["requested"] = "2026-11-10T12:00:00+00:00"
        (team.dir / "reviews" / "w1.json").write_text(json.dumps(r))
        findings = [{"id": "feat#1", "wos": ["w1"], "by": "Kong", "also": [], "state": "open"},
                    {"id": "feat#2", "wos": ["w1"], "by": "Perkins", "also": ["Kong"], "state": "closed"},
                    {"id": "feat#3", "wos": ["w1"], "by": "Kong", "also": [], "state": "dropped"},
                    {"id": "feat#4", "wos": ["w1"], "by": "Perkins", "also": [], "state": "open"}]
        for f in findings:
            f.update(time="2026-11-10T12:01:00+00:00", where="A/value:1", what="wrong result")
        with cl.FindingsLock(team):
            cl.save_findings(team, "feat", findings)
        call_reviewed(team, "w1")
        assert review(team, "w1")["reviewers"] == {"Kong": "findings"}
        assert json.loads((team.dir / "landed.log").read_text())["findings"] == ["feat#1", "feat#2"]


def test_kong_review_without_record_is_refused():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        with contextlib.redirect_stderr(io.StringIO()) as err:
            try: call_reviewed(team, "missing")
            except SystemExit as exc: assert exc.code == 5
            else: raise AssertionError("missing review accepted")
        assert "missing" in err.getvalue() and "Stage 3" in err.getvalue()


def finding_args(zone="A"):
    return SimpleNamespace(feature="feat", same_as=None, wo=["w1"], zone=zone, where="A/a.py:1", severity=2,
                           kind="spec", what="wrong", belongs="")


def test_stage3_finding_waits_for_verdict_to_notify():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp)); queue(team, "w1")
        row = review(team, "w1"); row["feature"] = "feat"
        (team.dir / "reviews" / "w1.json").write_text(json.dumps(row))
        team.notify.reset_mock()
        with patch.dict(os.environ, CODETEAM_SESSION="Kong"):
            cl.cmd_finding(team, finding_args())
        assert cl.find_finding(team, "feat#1")["state"] == "open"
        team.notify.assert_not_called()
        call_reviewed(team, "w1")
        assert team.notify.call_args.args[:2] == ("Coord-A", "REQUEST")
        assert "feat#1" in team.notify.call_args.args[2]


def test_owners_excludes_guard_and_perkins_from_default_and_configuration():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        assert cl.owners(team) == ["Nagatha"]
        team.cfg["review_after"] = {"owners": ["Kong", "Nagatha", "unknown", "Perkins"]}
        assert cl.owners(team) == ["Nagatha"]


def test_feature_round_notifies_nagatha_and_she_can_finish():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        cl.save_feature(team, {"feature": "w1", "tagged": False, "landed": [{"wo": "w1", "zone": "A", "hash": "hash", "time": "2026-01-01T00:00:00"}], "rounds": []})
        cl.features_due(team)
        assert [c.args[0] for c in team.notify.call_args_list] == ["Nagatha"]
        with patch.dict(os.environ, CODETEAM_SESSION="Nagatha"), patch.object(cl, "now", return_value="review-time"):
            cl.cmd_reviewed(team, SimpleNamespace(feature="w1"))
        assert cl.load_feature(team, "w1")["rounds"][0]["reviewed"] == {"Nagatha": "review-time"}


def test_pure_tool_made_reason_requires_record_and_every_trailer():
    assert cl.tool_made_reason({"wo": "docs-x"}, [cl.MADE_BY]) is None
    assert cl.tool_made_reason({"made_by": "codeteam-land"}, ["change"]) is None
    assert cl.tool_made_reason({"made_by": "codeteam-land"}, [cl.MADE_BY, "change"]) is None
    assert cl.tool_made_reason({"made_by": "codeteam-land"}, ["change\n\nMade-By: codeteam-land"]) == "made by codeteam-land"

def test_kong_finding_routes_to_coordinator_and_closes_on_landing():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        cl.save_feature(team, {"feature": "feat", "landed": [{"wo": "w1"}], "rounds": []})
        with patch.dict(os.environ, {"CODETEAM_SESSION": "Kong"}):
            cl.cmd_finding(team, finding_args())
        to, kind, text = team.notify.call_args.args
        assert (to, kind) == ("Coord-A", "REQUEST")
        assert text.startswith("FIX-FORWARD feat#1 | zone A | work orders w1 | sev 2 spec | A/a.py:1: wrong")
        assert cl.find_finding(team, "feat#1")["state"] == "open"
        team.cfg["review_after"] = {"enabled": False}
        with contextlib.nullcontext():
            cl.after_landing(team, [{"wo": "fix1", "fixes": ["feat#1"]}])
        assert cl.find_finding(team, "feat#1")["state"] == "closed"
        assert cl.find_finding(team, "feat#1")["fixed_by"] == "fix1"

def test_kong_orc_finding_routes_to_orchestrator():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        cl.save_feature(team, {"feature": "feat", "landed": [{"wo": "w1"}], "rounds": []})
        with patch.dict(os.environ, {"CODETEAM_SESSION": "Kong"}):
            cl.cmd_finding(team, finding_args("orc"))
        assert team.notify.call_args.args[:2] == ("Skippy", "REQUEST")
        assert "FIX-FORWARD feat#1" in team.notify.call_args.args[2]

def test_perkins_finding_still_routes_to_orchestrator():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        cl.save_feature(team, {"feature": "feat", "landed": [{"wo": "w1"}], "rounds": []})
        with patch.dict(os.environ, {"CODETEAM_SESSION": "Perkins"}):
            cl.cmd_finding(team, finding_args())
        assert team.notify.call_args.args[:2] == ("Skippy", "REQUEST")
        assert "Route to Coord-A" in team.notify.call_args.args[2]

def test_finding_accepts_landed_record_without_feature_review():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        (team.dir / "wo" / "w1.landed.json").write_text(json.dumps({"wo": "w1", "zone": "A", "feature": "feat"}))
        with patch.dict(os.environ, {"CODETEAM_SESSION": "Kong"}):
            try:
                cl.cmd_finding(team, finding_args())
            except SystemExit as exc:
                raise AssertionError(f"landed work order was refused: {exc}") from exc
        assert cl.find_finding(team, "feat#1")["state"] == "open"

def test_landing_record_carries_base_and_landed_at():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        entry = {"wo": "w1", "tip": "tip", "base": "base", "zones": ["A"]}
        records = {"w1": {"wo": "w1", "zone": "A"}}
        team.save_wo(records["w1"])
        with patch.object(cl, "git"), patch.object(cl, "cleanup_landing"), patch.object(cl, "now", return_value="landed-time"):
            cl.record_landing_members(team, entry, "old", records, [("w1", "merge")], False)
        landed = json.loads((team.dir / "wo" / "w1.landed.json").read_text())
        assert landed["landed_base"] == "base"
        assert landed["landed_at"] == "landed-time"

failed = 0
for test in [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]:
    try:
        test()
        print(f"  PASS {test.__name__}")
    except (Exception, SystemExit) as exc:
        failed += 1
        print(f"  FAIL {test.__name__}: {type(exc).__name__}: {exc}")
print(f"{failed} failed" if failed else "all passed")
sys.exit(1 if failed else 0)
