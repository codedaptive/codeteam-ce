#!/usr/bin/env -S python3 -u
"""Isolated feature-round and review-bookkeeping contracts (after_landing, the review owners, the tool-made reason,
the landing record): the unit tests (rule 11); git, where called, is faked. The tests that take the real
landing and findings locks (check_and_queue, reviewed, finding, the feature round) or run real git are in
tests/integration/land-v52-review.py."""
import importlib.machinery
import importlib.util
import json
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


def test_owners_excludes_guard_and_perkins_from_default_and_configuration():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        assert cl.owners(team) == ["Nagatha"]
        team.cfg["review_after"] = {"owners": ["Kong", "Nagatha", "unknown", "Perkins"]}
        assert cl.owners(team) == ["Nagatha"]


def test_pure_tool_made_reason_requires_record_and_every_trailer():
    assert cl.tool_made_reason({"wo": "docs-x"}, [cl.MADE_BY]) is None
    assert cl.tool_made_reason({"made_by": "codeteam-land"}, ["change"]) is None
    assert cl.tool_made_reason({"made_by": "codeteam-land"}, [cl.MADE_BY, "change"]) is None
    assert cl.tool_made_reason({"made_by": "codeteam-land"}, ["change\n\nMade-By: codeteam-land"]) == "made by codeteam-land"

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

def started_rounds():
    return [
        ({"feature": "alpha-security"}, {"n": 1, "reviewed": {}}, [
            {"wo": "a", "zone": "A", "hash": "ha", "time": "t", "review": "before"}]),
        ({"feature": "beta-ordinary"}, {"n": 1, "reviewed": {}}, [
            {"wo": "b", "zone": "A", "hash": "hb", "time": "t", "review": "before"}]),
        ({"feature": "gamma-security"}, {"n": 1, "reviewed": {}}, [
            {"wo": "c", "zone": "A", "hash": "hc", "time": "t", "review": "before"}]),
    ]


def test_notify_owners_sends_perkins_no_feature_round_with_security_paths():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp)); team.cfg["security_paths"] = ["auth/*"]
        with patch.object(cl, "out", return_value="auth/login.py\n"):
            cl.notify_owners(team, started_rounds())
        calls = [c.args[:2] for c in team.notify.call_args_list]
        assert calls == [("Nagatha", "REQUEST")], f"unexpected notifications: {calls}"


def test_notify_owners_sends_perkins_no_feature_round_without_security_paths():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        with patch.object(cl, "out", return_value="auth/login.py\n"):
            cl.notify_owners(team, started_rounds())
        assert [c.args[:2] for c in team.notify.call_args_list] == [("Nagatha", "REQUEST")]


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
