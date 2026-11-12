#!/usr/bin/env -S python3 -u
"""v5.4 record durability, guarded writes, and review-round boundaries with fake collaborators."""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_v54_records", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)


def team_at(root):
    manifest = root / "sample.toml"
    manifest.write_text(f'repo = "{root / "repo"}"\nworktree_root = "{root / "team"}"\n'
                        '[[lanes]]\nname = "A"\npath = "A"\n[[assistants]]\nname = "Perkins"\n'
                        '[land]\nsecurity_paths = ["A/auth*"]\nseed_index = false\n')
    team = cl.Team(manifest); team.notify = Mock()
    return team


def record(team, wo="w"):
    rec = {"wo": wo, "zone": "A", "tip": "T", "base": "B", "tree": str(team.root / wo),
           "branch": "wo/A/" + wo, "files": ["A/value"]}
    team.save_wo(rec)
    return rec


def test_stage2_record_has_contract_fields_and_rounding():
    assert cl.stage2_record([{"name": "compile A", "outcome": "PASS", "seconds": 1.24, "tail": ["noise"]},
                             {"name": "tests A", "outcome": "HUNG", "seconds": 2.36, "tail": []}]) == [
        {"step": "compile A", "result": "pass", "seconds": 1.2},
        {"step": "tests A", "result": "hung", "seconds": 2.4}]


def test_stage2_records_every_batch_in_order_including_failed_batch():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); rec = record(team)
        batches = [[{"name": "compile A", "outcome": "PASS", "seconds": 1.24, "tail": []}],
                   [{"name": "repo units", "outcome": "PASS", "seconds": 2.36, "tail": []}],
                   [{"name": "zone integration", "outcome": "FAIL", "seconds": 3.14, "tail": ["bad"]},
                    {"name": "repo integration", "outcome": "PASS", "seconds": 4.16, "tail": []}]]
        def run(tree, steps, env, **kwargs):
            rows = batches.pop(0)
            for row in reversed(rows):
                kwargs["on_result"](row)
            return (all(row["outcome"] == "PASS" for row in rows), [])
        with patch.object(cl, "duplicate_rulings", return_value=[]), patch.object(cl, "reach", return_value=["A"]), \
                patch.object(cl, "compile_steps", return_value=[("compile A", "c")]), \
                patch.object(cl, "repo_test_steps", return_value=[("repo units", "u")]), \
                patch.object(cl, "zone_tests", return_value=[("zone integration", "z")]), \
                patch.object(cl, "repo_integration_steps", return_value=[("repo integration", "r")]), \
                patch.object(cl, "team_env", return_value={}), patch.object(cl, "run_steps", side_effect=run):
            try: cl.check_integration(team, rec, False)
            except SystemExit as exc: assert exc.code == 3
            else: raise AssertionError("failed integration batch was accepted")
        assert team.wo("w")["stage2"] == [
            {"step": "compile A", "result": "pass", "seconds": 1.2},
            {"step": "repo units", "result": "pass", "seconds": 2.4},
            {"step": "zone integration", "result": "fail", "seconds": 3.1},
            {"step": "repo integration", "result": "pass", "seconds": 4.2}]
        assert batches == []


def test_landed_log_preserves_stage2_failed_then_fixed_history():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); rec = record(team)
        rec["stage2"] = [{"step": "tests A", "result": "fail", "seconds": 1.2},
                         {"step": "tests A", "result": "pass", "seconds": 0.8}]
        team.save_wo(rec)
        entry = {"wo": "w", "tip": "T", "base": "B", "zones": ["A"]}
        with patch.object(cl, "git"), patch.object(cl, "cleanup_landing"):
            cl.record_landing_members(team, entry, "OLD", {"w": rec}, [("w", "M")], False)
        row = json.loads((team.dir / "landed.log").read_text())
        assert row["stage2"] == [{"step": "tests A", "result": "fail", "seconds": 1.2},
                                 {"step": "tests A", "result": "pass", "seconds": 0.8}]


def test_unit_batch_is_recorded_before_its_failure_exits():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); rec = record(team)
        def run(tree, steps, env, **kwargs):
            kwargs["on_result"]({"name": "units A", "outcome": "FAIL", "seconds": 0.14, "tail": []})
            return False, []
        with patch.object(cl, "zone_tests", return_value=[("units A", "u")]), patch.object(cl, "team_env", return_value={}), \
                patch.object(cl, "run_steps", side_effect=run):
            try: cl.test_units(team, rec)
            except SystemExit as exc: assert exc.code == 3
            else: raise AssertionError("failed units accepted")
        assert team.wo("w")["stage2"] == [{"step": "units A", "result": "fail", "seconds": 0.1}]


def test_guarded_refs_order_and_deduplication():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        assert cl.guarded_refs(team) == ["refs/heads/landing", "refs/heads/integration", "refs/heads/main"]
        team.landing = "integration"
        assert cl.guarded_refs(team) == ["refs/heads/integration", "refs/heads/main"]
        team.cfg["guard_base"] = False
        assert cl.guarded_refs(team) == ["refs/heads/integration"]


def test_guard_hook_requires_tool_marker_but_lab_has_no_marker_rule():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); team = team_at(root); common = root / "git"
        with patch.object(cl, "out", return_value=str(common)), patch.object(cl, "git"):
            cl.cmd_install_hook(team, SimpleNamespace())
        hook = (common / "codeteam-land-guard").read_text()
        assert '[ "${CODETEAM_LAND_TOOL}" = "1" ]' in hook
        assert hook.index('"${CODETEAM_LAND_TOOL}"') < hook.index('adopt=')
        assert 'integration must copy base' in hook
        assert 'git merge-base --is-ancestor "$new" "refs/heads/landing"' in hook
        team.lab = True; team.landing = team.integration = "main"
        with patch.object(cl, "out", return_value=str(common)), patch.object(cl, "git"):
            cl.cmd_install_hook(team, SimpleNamespace())
        assert "CODETEAM_LAND_TOOL" not in (common / "codeteam-land-guard").read_text()


def test_move_landing_uses_compare_and_move_and_marker():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        with patch.object(cl, "git", return_value=SimpleNamespace(returncode=1, stderr="moved")) as git:
            assert cl.move_landing(team, "N", "O") is False
        assert git.call_args.args == (team.repo, "update-ref", "refs/heads/landing", "N", "O")
        assert git.call_args.kwargs["env"]["CODETEAM_LAND_TOOL"] == "1"
        assert git.call_args.kwargs["check"] is False


def test_land_entry_pending_review_refuses_before_any_git_or_record_read():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); p = team.dir / "queue" / "w.json"
        p.write_text(json.dumps({"wos": ["w"], "wo": "w", "tip": "T", "base": "B", "zones": ["A"], "review": "pending"}))
        with patch.object(cl, "git") as git, patch.object(team, "wo") as wo:
            assert cl.land_entry(team, p) == 5
        git.assert_not_called(); wo.assert_not_called()
        assert p.exists()


def test_review_range_excludes_both_branches_and_this_reviewers_seen_tips():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        with patch.object(cl, "out", return_value="new\n") as out:
            assert cl.review_range(team, "TIP", ["K1", "K2"]) == ["new"]
        assert out.call_args.args == (team.repo, "rev-list", "--no-merges", "TIP", "--not", "refs/heads/landing", "refs/heads/integration", "K1", "K2")


def test_findings_cannot_be_resubmitted_without_a_new_commit():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); rec = record(team)
        previous = {"stage": 3, "wo": "w", "state": "findings", "reviewers": {"Kong": "findings"}, "seen": {"Kong": ["T"]}}
        (team.dir / "reviews" / "w.json").write_text(json.dumps(previous))
        with patch.object(cl, "review_range", return_value=[]), patch.object(cl, "review_files", return_value=[]), \
                patch.object(cl, "all_findings", return_value=[{"id": "w#1", "wos": ["w"], "state": "open"}]):
            try: cl.stage3_record(team, rec)
            except SystemExit as exc: assert exc.code == 3
            else: raise AssertionError("resubmission passed over the finding without a commit")
        assert list((team.dir / "queue").glob("*.json")) == []


def test_clean_new_review_closes_only_earlier_stage3_findings():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); record(team)
        row = {"stage": 3, "wo": "w", "zone": "A", "tip": "F", "reviewers": {"Kong": "pending"},
               "seen": {"Kong": ["T"]}, "requested": "2026-11-10T13:00:00+00:00", "state": "pending"}
        path = team.dir / "reviews" / "w.json"; path.write_text(json.dumps(row))
        with cl.FindingsLock(team):
            cl.save_findings(team, "w", [{"id": "w#1", "wos": ["w"], "stage": 3, "by": "Kong", "also": [], "state": "open", "time": "2026-11-10T12:00:00+00:00"},
                                        {"id": "w#2", "wos": ["w"], "by": "Nagatha", "also": [], "state": "open", "time": "2026-11-10T12:00:00+00:00"}])
        cl.guard_reviewed(team, "w", "Kong")
        assert cl.find_finding(team, "w#1")["state"] == "closed"
        assert cl.find_finding(team, "w#1")["reason"] == "fixed before landing"
        assert cl.find_finding(team, "w#2")["state"] == "open"
        assert json.loads(path.read_text())["seen"] == {"Kong": ["T", "F"]}


def test_promote_intent_replays_effects_after_ref_moves_and_uses_recorded_C():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); refs = {"main": "B", "integration": "B"}
        path = team.dir / "promote.json"
        path.write_text(json.dumps({"C": "C", "old_integration": "B", "time": "earlier"}))
        calls = []
        def out(repo, *args):
            if args[0] == "worktree": return ""
            return "main" if args[:2] == ("rev-parse", "--abbrev-ref") else refs[args[-1]]
        def git(repo, *args, **kwargs):
            if args[0] == "merge":
                assert path.exists(); refs["main"] = "C"
            if args[0] == "update-ref":
                assert path.exists(); refs["integration"] = args[2]
                assert kwargs["env"]["CODETEAM_LAND_TOOL"] == "1"
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        def anc(t):
            return lambda a, b: a == b or (a == "C" and b == "main" and refs["main"] == "C") or (a, b) == ("B", "C")
        def restart(*args):
            calls.append("restart")
            if len(calls) == 1: raise RuntimeError("interrupted after refs moved")
        with patch.object(cl, "out", side_effect=out), patch.object(cl, "git", side_effect=git), \
                patch.object(cl, "ancestry", side_effect=anc), patch.object(cl, "promoted_notices") as notices, \
                patch.object(cl, "after_promote", side_effect=restart), patch.object(cl, "stamp_docs", return_value=None) as stamp:
            try: cl.stage7(team, "IGNORED")
            except RuntimeError: pass
            else: raise AssertionError("interruption not exercised")
            assert path.exists() and refs == {"main": "C", "integration": "C"}
            assert cl.stage7(team, "ALSO-IGNORED") == "C"
        assert not path.exists()
        assert notices.call_count == 2
        assert all(call.args == (team, "B", "C") for call in notices.call_args_list)
        stamp.assert_called_once_with(team, "C", "B")


def test_committed_stamp_replay_keeps_tree_and_resubmits_detached_land():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); rec = record(team, "docs-stamp-C")
        rec["made_by"] = "codeteam-land"; team.save_wo(rec)
        with patch.object(cl, "out", return_value="stamp\n\nMade-By: codeteam-land"), patch.object(cl, "spawn") as spawn, \
                patch.object(cl, "cmd_wo_retire") as retire, patch.object(cl, "cmd_wo_cut") as cut:
            assert cl.resume_stamp(team, "docs-stamp-C") is True
        assert "land docs-stamp-C" in spawn.call_args.args[0]
        retire.assert_not_called(); cut.assert_not_called()
        assert team.wo_file("docs-stamp-C").exists()


def test_queued_stamp_replay_does_not_cancel_recut_or_resubmit():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); record(team, "docs-stamp-C")
        (team.dir / "queue" / "stamp.json").write_text(json.dumps({"wos": ["docs-stamp-C"]}))
        with patch.object(cl, "spawn") as spawn, patch.object(cl, "cmd_wo_retire") as retire:
            assert cl.resume_stamp(team, "docs-stamp-C") is True
        spawn.assert_not_called(); retire.assert_not_called()


def test_move_replay_observes_effects_before_marking_steps_done():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); path = team.dir / "v54-move.json"
        rec = {"old_integration": "OLD", "base": "BASE", "started": "earlier", "done": []}
        path.write_text(json.dumps(rec))
        (team.dir / "recheck.jsonl").write_text(json.dumps({"move": True, "M": "OLD", "done": "finished"}) + "\n")
        backlog = {"zone": "A", "from": "BASE", "to": "OLD", "state": "pending", "requested": "already sent"}
        (team.dir / "reviews" / "backlog-A.json").write_text(json.dumps(backlog))
        def out(repo, *args):
            return "BASE" if args[0] == "rev-parse" else "A/value"
        with patch.object(cl, "git", return_value=SimpleNamespace(returncode=0, stdout="OLD")) as git, \
                patch.object(cl, "out", side_effect=out), patch.object(cl, "cmd_install_hook") as hook:
            cl.migrate_v54_steps(team, path, rec)
        assert not any(call.args[1] == "update-ref" for call in git.call_args_list)
        hook.assert_called_once_with(team, cl.argparse_ns())
        assert json.loads(path.read_text())["done"] == ["landing", "hook", "integration", "recheck", "backlog"]
        assert len(cl.read_recheck(team)) == 1
        team.notify.assert_not_called()


def test_move_over_inherited_files_do_not_count_as_work_order_wall_edits():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); rec = record(team)
        def out(repo, *args):
            return "T" if args[0] == "rev-parse" else ""
        with patch.object(cl, "out", side_effect=out), patch.object(cl, "changed_files", return_value=["A/own", "B/inherited"]), \
                patch.object(cl, "review_range", return_value=["T"]), patch.object(cl, "review_files", return_value=["A/own"]), \
                patch.object(cl, "zone_docs", return_value=[]), patch.object(cl, "guard_walls", return_value=None):
            assert cl.check_work_order(team, rec) == ["A/own"]


def test_intent_write_is_atomic_if_interrupted_before_replace():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "promote.json"
        path.write_text(json.dumps({"C": "OLD", "old_integration": "B", "time": "earlier"}))
        new = {"C": "NEW", "old_integration": "OLD", "time": "later"}
        with patch.object(Path, "replace", side_effect=RuntimeError("interrupted")):
            try: cl.save_record(path, new)
            except RuntimeError: pass
            else: raise AssertionError("interruption not exercised")
        assert json.loads(path.read_text()) == {"C": "OLD", "old_integration": "B", "time": "earlier"}
        cl.save_record(path, new)
        assert json.loads(path.read_text()) == {"C": "NEW", "old_integration": "OLD", "time": "later"}


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
