#!/usr/bin/env -S python3 -u
"""Move-over guards and ancestry boundaries with isolated teams."""
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

os.environ["CODETEAM_QUEUE_DIR"] = str(Path(tempfile.mkdtemp(prefix="land-guard-queue-")) / "queue")
ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_v54_guard", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)

NOT_MOVED = "not moved to v5.4: run migrate-v54"


def team_at(root):
    repo = root / "repo"
    repo.mkdir()
    manifest = root / "sample.toml"
    manifest.write_text(f'repo = "{repo}"\nworktree_root = "{root / "team"}"\n'
                        '[land]\norchestrator = "Skippy"\n')
    team = cl.Team(manifest)
    team.notify = Mock()
    return team


def git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def moved_team(root):
    team = team_at(root)
    git(team.repo, "init", "-q", "-b", "main")
    commits = []
    for name in ("before", "move", "landing"):
        git(team.repo, "commit", "-q", "--allow-empty", "-m", name)
        commits.append(git(team.repo, "rev-parse", "HEAD"))
    git(team.repo, "branch", "landing")
    (team.dir / "v54-move.json").write_text(json.dumps({"old_integration": commits[1]}))
    (team.dir / "recheck.jsonl").write_text(json.dumps({"M": commits[1], "move": True, "done": "yes"}) + "\n")
    return team, commits


def rows(team, *values):
    (team.dir / "validation-results.jsonl").write_text("".join(json.dumps(row) + "\n" for row in values))


def passed(commit, tagged=False):
    row = {"commit": commit, "result": "pass", "tests": []}
    if tagged:
        row["v54"] = True
    return row


def runner_unmoved(name):
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        args = SimpleNamespace(once=True)
        output = io.StringIO()
        with contextlib.ExitStack() as stack:
            for attr, value in (("drive_buildq_restart", None), ("runner_restart", False), ("halted", False),
                                ("queue_maintenance", (0, 0)), ("advance_queue", False),
                                ("read_recheck", [{"M": "T", "wo": "w"}]),
                                ("stage6_target", "T"), ("alpha_cfg", {"local": True}),
                                ("validate_due", True), ("run_validation_tick", (None, None))):
                stack.enter_context(patch.object(cl, attr, return_value=value))
            recheck = stack.enter_context(patch.object(cl, "recheck_one"))
            validate = stack.enter_context(patch.object(cl, "validate_one"))
            land = stack.enter_context(patch.object(cl, "land_entry"))
            say = stack.enter_context(patch.object(cl, "spawn"))
            stack.enter_context(patch.object(cl.time, "time", return_value=10000))
            stack.enter_context(patch.object(cl.time, "sleep"))
            stack.enter_context(contextlib.redirect_stdout(output))
            stack.enter_context(contextlib.redirect_stderr(output))
            runner = getattr(cl, "cmd_" + name.replace("-", "_"))
            runner(team, args)
            first = output.getvalue()
            output.seek(0); output.truncate()
            runner(team, args)
            second = output.getvalue()
            assert NOT_MOVED in first, f"{name} did not print the unmoved notice"
            assert NOT_MOVED not in second, f"{name} repeated the notice within an hour"
            assert NOT_MOVED not in output.getvalue(), f"{name} printed twice"
            cl.queue_maintenance.assert_not_called()
            cl.advance_queue.assert_not_called()
            cl.stage6_target.assert_not_called()
            recheck.assert_not_called(); validate.assert_not_called(); land.assert_not_called()
            team.notify.assert_not_called(); say.assert_not_called()
            output.seek(0); output.truncate()
            cl.runner_restart.return_value = True
            cl.halted.reset_mock()
            runner(team, args)
            cl.halted.assert_not_called()
            assert output.getvalue() == "", "restart must be consumed before the guard"
            cl.runner_restart.return_value = False
            cl.halted.return_value = True
            output.seek(0); output.truncate()
            runner(team, args)
            assert output.getvalue() == "", "halt must be honoured before the guard"


def test_queue_runner_unmoved_idles_and_preserves_restart_and_halt():
    runner_unmoved("queue-run")


def test_recheck_runner_unmoved_idles_and_preserves_restart_and_halt():
    runner_unmoved("recheck-run")


def test_validate_runner_unmoved_idles_and_preserves_restart_and_halt():
    runner_unmoved("validate-run")


def test_each_unmoved_runner_consumes_real_restart_request():
    for name in ("queue-run", "recheck-run", "validate-run"):
        with tempfile.TemporaryDirectory() as tmp:
            team = team_at(Path(tmp))
            directory = team.dir / "restart"
            directory.mkdir()
            request = directory / f"{name}.json"
            request.write_text(json.dumps({"requested_ts": 1, "tip": "T"}))
            runner = getattr(cl, "cmd_" + name.replace("-", "_"))
            with patch.object(cl, "drive_buildq_restart"), patch.object(cl, "halted") as halt, \
                    patch.object(cl, "queue_maintenance") as maintenance, \
                    patch.object(cl, "stage6_target") as validate, patch.object(cl, "recheck_one") as recheck:
                runner(team, SimpleNamespace(once=True))
            assert not request.exists(), f"{name} did not consume its restart request"
            halt.assert_not_called(); maintenance.assert_not_called(); validate.assert_not_called(); recheck.assert_not_called()


def refused(call):
    output = io.StringIO()
    with contextlib.redirect_stderr(output):
        try:
            call()
        except SystemExit as exc:
            assert exc.code != 0, "command exited successfully instead of refusing"
            return output.getvalue() + str(exc)
    raise AssertionError("command did not refuse")


def test_land_refuses_unmoved_before_stage_work():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        with patch.object(cl, "check_and_queue") as work:
            message = refused(lambda: cl.cmd_land(team, SimpleNamespace(untested=False, wo="w", with_=None)))
        assert NOT_MOVED in message, message
        work.assert_not_called()


def test_land_one_refuses_unmoved_before_stage_work():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        with patch.object(cl, "prune_queue") as work:
            message = refused(lambda: cl.cmd_land_one(team, SimpleNamespace(wo="w")))
        assert NOT_MOVED in message, message
        work.assert_not_called()


def test_promote_refuses_unmoved_without_intent():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        with patch.object(cl, "stage7") as work:
            message = refused(lambda: cl.cmd_promote(team, SimpleNamespace(hash="C")))
        assert NOT_MOVED in message, message
        work.assert_not_called()


def test_promote_replays_intent_even_when_unmoved():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        (team.dir / "promote.json").write_text(json.dumps({"C": "C", "old_integration": "B", "time": "now"}))
        with patch.object(cl, "finish_promotion") as finish:
            assert cl.cmd_promote(team, SimpleNamespace(hash="other")) == "C"
        assert finish.call_args.args[1]["C"] == "C"
        assert not (team.dir / "promote.json").exists()


def test_lab_promote_is_not_subject_to_move_guard():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        team.manifest.write_text('mode = "lab"\n' + team.manifest.read_text())
        team = cl.Team(team.manifest)
        with patch.object(cl, "promotion_target", return_value="C"), patch.object(cl, "stage7") as promote:
            cl.cmd_promote(team, SimpleNamespace(hash=None))
        promote.assert_called_once_with(team, "C")


def test_lab_land_is_not_subject_to_move_guard():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); team.lab = True
        with patch.object(cl, "check_and_queue") as work:
            cl.cmd_land(team, SimpleNamespace(untested=False, wo="w", with_=None))
        work.assert_called_once()


def test_migrate_refuses_pending_promotion_before_creating_move():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        (team.dir / "promote.json").write_text(json.dumps({"C": "C"}))
        with patch.object(cl, "integration_holders", return_value=[]), \
                patch.object(cl, "migrate_v54_steps") as work:
            message = refused(lambda: cl.cmd_migrate_v54(team, SimpleNamespace()))
        assert "promote" in message and str(team.manifest) in message, message
        assert not (team.dir / "v54-move.json").exists()
        work.assert_not_called()


def test_move_boundary_prevents_stage6_falling_back_before_T():
    with tempfile.TemporaryDirectory() as tmp:
        team, (before, T, L1) = moved_team(Path(tmp))
        (team.dir / "recheck.jsonl").write_text(json.dumps({"M": T, "move": True}) + "\n")
        assert cl.stage6_target(team) is None, "a pending move cannot validate T~1"


def test_done_move_with_pending_at_T_does_not_validate_before_T():
    with tempfile.TemporaryDirectory() as tmp:
        team, (before, T, L1) = moved_team(Path(tmp))
        (team.dir / "recheck.jsonl").write_text(
            json.dumps({"M": T, "move": True, "done": "yes"}) + "\n"
            + json.dumps({"M": T, "wo": "w"}) + "\n")
        target = cl.stage6_target(team)
        assert target is None, f"pending T must hold Stage 6, not return {target} (before T: {before})"


def test_done_move_with_pending_at_L1_allows_T():
    with tempfile.TemporaryDirectory() as tmp:
        team, (before, T, L1) = moved_team(Path(tmp))
        (team.dir / "recheck.jsonl").write_text(
            json.dumps({"M": T, "move": True, "done": "yes"}) + "\n"
            + json.dumps({"M": L1, "wo": "w"}) + "\n")
        assert cl.stage6_target(team) == T, "pending L1 must not block T"


def test_move_boundary_prevents_promotion_target_before_T():
    with tempfile.TemporaryDirectory() as tmp:
        team, (before, T, L1) = moved_team(Path(tmp))
        rows(team, passed(before, tagged=True))
        assert cl.promotion_target(team) is None, "T~1 is before the move even with a tagged pass"


def test_explicit_promote_before_T_names_move_tip():
    with tempfile.TemporaryDirectory() as tmp:
        team, (before, T, L1) = moved_team(Path(tmp))
        rows(team, passed(before, tagged=True))
        with patch.object(cl, "integration_holders", return_value=[]):
            message = refused(lambda: cl.cmd_promote(team, SimpleNamespace(hash=before)))
        assert before in message and T in message and "before" in message, message


def test_promotion_target_ignores_untagged_pass_at_T():
    with tempfile.TemporaryDirectory() as tmp:
        team, (before, T, L1) = moved_team(Path(tmp))
        rows(team, passed(T))
        assert cl.promotion_target(team) is None, "a v5.2 pass at T is not v5.4 validation"


def test_check_promotion_ignores_untagged_pass_at_T():
    with tempfile.TemporaryDirectory() as tmp:
        team, (before, T, L1) = moved_team(Path(tmp))
        rows(team, passed(T))
        with patch.object(cl, "integration_holders", return_value=[]):
            try:
                cl.check_promotion(team, T)
            except cl.PromotionRefused as exc:
                assert "Stage 6" in str(exc), str(exc)
            else:
                raise AssertionError("untagged pass at T must not allow promotion")


def test_validate_runner_treats_untagged_pass_at_T_as_due():
    with tempfile.TemporaryDirectory() as tmp:
        team, (before, T, L1) = moved_team(Path(tmp))
        rows(team, passed(T))
        with patch.object(cl, "drive_buildq_restart"), patch.object(cl, "runner_restart", return_value=False), \
                patch.object(cl, "halted", return_value=False), patch.object(cl, "stage6_target", return_value=T), \
                patch.object(cl, "alpha_cfg", return_value={"local": True}), \
                patch.object(cl, "run_validation_tick", return_value=({"commit": T}, None)) as run:
            cl.cmd_validate_run(team, SimpleNamespace(once=True))
        assert run.call_count == 1, "T must be validated again after the move"


def test_validate_one_tags_non_lab_result():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        with patch.object(cl, "check_at", return_value={"hash": "T", "result": "pass", "time": "now"}), \
                patch.object(cl, "apply_validation_findings"):
            cl.validate_one(team, {"local": True}, "T")
        row = json.loads((team.dir / "validation-results.jsonl").read_text())
        assert row.get("v54") is True, "new non-lab validations must be tagged"


def test_move_finding_holds_T_and_L1_until_closed_at_candidate():
    with tempfile.TemporaryDirectory() as tmp:
        team, (before, T, L1) = moved_team(Path(tmp))
        finding = {"id": "move#1", "test": "suite", "Ms": [T], "state": "open"}
        is_ancestor = cl.ancestry(team)
        assert cl.unfixed_failures(T, [finding], {}, is_ancestor) == ["move#1"]
        assert cl.unfixed_failures(L1, [finding], {}, is_ancestor) == ["move#1"]
        closed = dict(finding, state="closed", closed_at=L1)
        assert cl.unfixed_failures(T, [closed], {}, is_ancestor) == ["move#1"]
        assert cl.unfixed_failures(L1, [closed], {}, is_ancestor) == []


def test_move_checkout_failure_remains_pending_and_notifies_once():
    with tempfile.TemporaryDirectory() as tmp:
        team, (before, T, L1) = moved_team(Path(tmp))
        row = {"M": T, "move": True, "wo": "v54-move", "overlapping": [], "zones": []}
        (team.dir / "recheck.jsonl").write_text(json.dumps(row) + "\n")
        with patch.object(cl, "itest_checkout", side_effect=cl.CheckoutFailed(T, "failed")):
            cl.recheck_one(team, row)
            current = cl.read_recheck(team)[0]
            assert "done" not in current, "checkout failure must leave the move pending"
            assert current.get("checkout_failed"), "checkout failure must record its notice"
            cl.recheck_one(team, current)
        assert team.notify.call_count == 1, "checkout NOTE must be sent once per move line"
        assert cl.stage6_target(team) is None, "pending move must hold Stage 6"


def test_recheck_runner_sleeps_after_pending_move_checkout_failure():
    class StopLoop(Exception):
        pass

    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        team.cfg["poll_s"] = 7
        row = {"M": "T", "move": True, "wo": "v54-move", "overlapping": [], "zones": []}
        (team.dir / "recheck.jsonl").write_text(json.dumps(row) + "\n")
        with patch.object(cl, "v54_unmoved", return_value=False), \
                patch.object(cl, "halted", side_effect=[False, StopLoop()]), \
                patch.object(cl, "runner_restart", return_value=False), \
                patch.object(cl, "stage_admit", return_value=contextlib.nullcontext()), \
                patch.object(cl, "itest_checkout", side_effect=cl.CheckoutFailed("T", "failed")) as checkout, \
                patch.object(cl.time, "sleep") as sleep:
            try:
                cl.cmd_recheck_run(team, SimpleNamespace(once=False))
            except StopLoop:
                pass
        checkout.assert_called_once_with(team, "T")
        assert "done" not in cl.read_recheck(team)[0], "failed checkout must leave the move pending"
        sleep.assert_called_once_with(7)


def test_move_findings_exception_leaves_line_pending():
    with tempfile.TemporaryDirectory() as tmp:
        team, (before, T, L1) = moved_team(Path(tmp))
        row = {"M": T, "move": True, "wo": "v54-move", "overlapping": [], "zones": []}
        (team.dir / "recheck.jsonl").write_text(json.dumps(row) + "\n")
        with patch.object(cl, "itest_checkout", return_value=team.repo), \
                patch.object(cl, "recheck_steps", return_value=([], [])), patch.object(cl, "team_env", return_value={}), \
                patch.object(cl, "step_results", return_value=[]), patch.object(cl, "landed_rec", return_value={}), \
                patch.object(cl, "apply_recheck_findings", side_effect=ValueError("failed")):
            cl.recheck_one(team, row)
        assert "done" not in cl.read_recheck(team)[0], "unrecorded findings must leave the move pending"


if __name__ == "__main__":
    failed = 0
    for name, test in list(globals().items()):
        if name.startswith("test_") and callable(test):
            try:
                test()
                print(f"PASS {name}")
            except (Exception, SystemExit) as exc:
                failed += 1
                print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"{failed} failed")
    sys.exit(bool(failed))
