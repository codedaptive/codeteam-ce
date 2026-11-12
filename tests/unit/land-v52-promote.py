#!/usr/bin/env -S python3 -u
"""Isolated Stage 7 promotion and validation hand-off contracts."""
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

# Restart markers and stage admissions live beside the queue; keep them out of the checkout.
os.environ["CODETEAM_QUEUE_DIR"] = str(Path(tempfile.mkdtemp(prefix="land-queue-")) / "queue")

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_promote", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)

# These isolated stage fixtures represent teams that have already moved over.
cl.v54_unmoved = Mock(return_value=False)

C = "0123456789abcdef"
STAMP = "fedcba9876543210"


def row(commit=C, result="pass", tests=None):
    return {"time": "now", "commit": commit, "result": result, "seconds": 1,
            "tests": tests if tests is not None else [{"name": "suite", "result": "pass", "seconds": 1}]}


def team_at(root):
    repo = root / "repo"
    repo.mkdir()
    manifest = root / "sample.toml"
    manifest.write_text(f'repo = "{repo}"\nworktree_root = "{root / "team"}"\n'
                        '[[assistants]]\nname = "Backporter"\nrole = "backporter"\n'
                        '[land]\norchestrator = "Skippy"\n')
    team = cl.Team(str(manifest))
    team.notify = Mock()
    return team


def save_rows(team, rows):
    (team.dir / "validation-results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def git_before_base(repo, *args, **kwargs):
    if args[:2] == ("merge-base", "--is-ancestor"):
        return SimpleNamespace(returncode=0 if args[-1] == "landing" or args[-2:] == ("base-old", "base-old") else 1, stdout="", stderr="")
    return SimpleNamespace(returncode=0, stdout="", stderr="")


def fake_out(repo, *args, **kwargs):
    if args[:2] == ("rev-parse", "--abbrev-ref"):
        return "main"
    return "" if args[0] == "diff" else "base-old"


def test_stage6_passed_newest_row_for_commit_decides():
    assert cl.stage6_passed([row(result="fail"), row(commit="other"), row()], C) is True
    assert cl.stage6_passed([row(), row(commit="other"), row(result="fail")], C) is False


def test_stage6_passed_requires_every_test_to_pass():
    for result in ("fail", "hung", "error"):
        tests = [{"name": "one", "result": "pass"}, {"name": "two", "result": result}]
        assert cl.stage6_passed([row(tests=tests)], C) is False, result


def test_stage6_passed_rejects_nonpassing_run_results():
    for result in ("fail", "hung", "error"):
        assert cl.stage6_passed([row(result=result)], C) is False, result


def test_stage6_passed_rejects_missing_commit():
    assert cl.stage6_passed([row(commit="other")], C) is False


def test_stage7_names_every_unfixed_test_failure_before_git():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); save_rows(team, [row()])
        with patch.object(cl, "unfixed_failures", return_value=["feat#1", "other#2"]), patch.object(cl, "git") as git:
            try: cl.stage7(team, C)
            except cl.PromotionRefused as exc: assert "feat#1" in str(exc) and "other#2" in str(exc)
            else: raise AssertionError("Stage 7 accepted unfixed test failures")
        git.assert_not_called()


def test_stage7_refuses_without_passing_validation():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        save_rows(team, [row(result="fail")])
        with patch.object(cl, "git") as git, contextlib.redirect_stderr(io.StringIO()):
            try:
                cl.stage7(team, C)
            except cl.PromotionRefused as exc:
                assert str(exc) == "0123456789abcdef has no passing Stage 6 validation; every test must pass"
            else:
                raise AssertionError("Stage 7 accepted failing validation")
        git.assert_not_called()


def test_stage7_refuses_commit_not_on_landing():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        save_rows(team, [row()])
        with patch.object(cl, "git", return_value=SimpleNamespace(returncode=1, stdout="", stderr="")) as git, \
                patch.object(cl, "out", side_effect=fake_out), patch.object(cl, "stamp_docs") as stamp, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            try:
                cl.stage7(team, C)
            except cl.PromotionRefused as exc:
                assert str(exc) == "0123456789 is not on landing"
            else:
                raise AssertionError("Stage 7 accepted a commit outside integration")
        assert err.getvalue() == ""
        assert not any(call.args[1:2] == ("merge",) for call in git.call_args_list)
        stamp.assert_not_called()
        team.notify.assert_not_called()


def test_stage7_refuses_checkout_not_on_base_branch():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        save_rows(team, [row()])
        with patch.object(cl, "git", side_effect=git_before_base) as git, \
                patch.object(cl, "out", return_value="other-branch"), patch.object(cl, "stamp_docs") as stamp, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            try:
                cl.stage7(team, C)
            except cl.PromotionRefused as exc:
                assert "is not on main" in str(exc)
            else:
                raise AssertionError("Stage 7 accepted a checkout outside the base branch")
        assert err.getvalue() == ""
        assert not any(call.args[1:2] == ("merge",) for call in git.call_args_list)
        stamp.assert_not_called()
        team.notify.assert_not_called()


def test_stage7_records_promoted_commit_and_base_in_landed_log():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        save_rows(team, [row()])
        with patch.object(cl, "git", side_effect=git_before_base), patch.object(cl, "out", side_effect=fake_out), \
                patch.object(cl, "stamp_docs", return_value=STAMP), contextlib.redirect_stdout(io.StringIO()):
            cl.stage7(team, C)
        rows = [json.loads(line) for line in (team.dir / "landed.log").read_text().splitlines()]
        assert len(rows) == 1
        assert rows[0]["promote"] == "0123456789abcdef"
        assert rows[0]["to"] == "main"


def test_stage7_stamps_but_promotes_validated_commit():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        save_rows(team, [row()])
        with patch.object(cl, "git", side_effect=git_before_base) as git, \
                patch.object(cl, "out", side_effect=fake_out), \
                patch.object(cl, "stamp_docs", return_value=STAMP) as stamp, \
                contextlib.redirect_stdout(io.StringIO()):
            assert cl.stage7(team, C) == C
        stamp.assert_called_once_with(team, C, "base-old")
        merges = [call.args for call in git.call_args_list if len(call.args) > 1 and call.args[1] == "merge"]
        assert len(merges) == 1 and merges[0][-1] == C and "--ff-only" in merges[0]
        assert STAMP not in merges[0]


def test_stage7_pushed_notice_names_validated_commit_and_stage6():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        save_rows(team, [row()])
        with patch.object(cl, "git", side_effect=git_before_base), patch.object(cl, "out", side_effect=fake_out), \
                patch.object(cl, "stamp_docs", return_value=None), contextlib.redirect_stdout(io.StringIO()):
            cl.stage7(team, C)
        messages = [call.args for call in team.notify.call_args_list if call.args[1] == "PUSHED"]
        assert ("Skippy", "PUSHED", "main promoted to 0123456789 (Stage 6 passed at 0123456789).") in messages
        assert any(args[0] == "Backporter" and "0123456789" in args[2] for args in messages)


def test_stage7_base_already_at_or_past_commit_does_nothing():
    for base in (C, "base-descendant"):
        with tempfile.TemporaryDirectory() as tmp:
            team = team_at(Path(tmp))
            save_rows(team, [row()])
            def out(repo, *args, **kwargs):
                return "main" if args[:2] == ("rev-parse", "--abbrev-ref") else base
            with patch.object(cl, "git", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")) as git, \
                    patch.object(cl, "out", side_effect=out), patch.object(cl, "stamp_docs") as stamp:
                cl.stage7(team, C)
            assert not any(call.args[1:2] == ("merge",) for call in git.call_args_list)
            stamp.assert_not_called()
            team.notify.assert_not_called()


def test_cmd_promote_default_uses_newest_passing():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        save_rows(team, [row(commit="old"), row(), row(commit="bad", result="fail")])
        with patch.object(cl, "git", side_effect=git_before_base) as git, patch.object(cl, "out", side_effect=fake_out), \
                patch.object(cl, "stamp_docs", return_value=None), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            try:
                cl.cmd_promote(team, SimpleNamespace(hash=None))
            except SystemExit as exc:
                raise AssertionError("latest passing validation was refused") from exc
        assert any(call.args[1:2] == ("merge",) and call.args[-1] == C for call in git.call_args_list)


def test_cmd_promote_refuses_explicit_hash_without_validation():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        (team.dir / "green").write_text(C + "\n")
        with patch.object(cl, "Team", return_value=team), patch.object(cl, "git", side_effect=git_before_base) as git, \
                patch.object(cl, "out", side_effect=fake_out), patch.object(cl, "stamp_docs", return_value=None), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                cl.main([str(team.manifest), "promote", C])
            except SystemExit as exc:
                assert exc.code != 0
            else:
                raise AssertionError("promote accepted an unvalidated hash")
        assert not any(call.args[1:2] == ("merge",) for call in git.call_args_list)


def test_cmd_promote_rejects_override_flag():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        with patch.object(cl, "Team", return_value=team), contextlib.redirect_stderr(io.StringIO()):
            try:
                cl.main([str(team.manifest), "promote", C, "--force"])
            except SystemExit as exc:
                assert exc.code != 0
            else:
                raise AssertionError("promote accepted --force")


def test_greens_api_removed():
    assert not hasattr(cl, "greens"), "obsolete green promotion input remains"


def run_validation(team, result, stage7):
    with patch.object(cl, "halted", return_value=False), patch.object(cl, "stage6_target", return_value=C), \
            patch.object(cl, "alpha_cfg", return_value={"local": True}), patch.object(cl, "validate_due", return_value=True), \
            patch.object(cl, "validate_one", return_value=result), patch.object(cl, "stage7", stage7, create=True):
        return cl.cmd_validate_run(team, SimpleNamespace(once=True))


def test_validate_run_promotes_passing_commit():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        promote = Mock()
        run_validation(team, row(), promote)
        promote.assert_called_once_with(team, C)


def test_validate_run_does_not_promote_failing_test_row():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        promote = Mock()
        run_validation(team, row(tests=[{"name": "suite", "result": "fail"}]), promote)
        promote.assert_not_called()


def test_validate_run_does_not_promote_failing_run():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        promote = Mock()
        run_validation(team, row(result="fail"), promote)
        promote.assert_not_called()


def test_validate_run_consults_stage7_even_with_review_findings_open():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        promote = Mock()
        save_finding(team, "feat", {"id": "feat#1", "state": "open", "wos": ["w1"]})
        run_validation(team, row(), promote)
        promote.assert_called_once_with(team, C)


def test_validate_run_logs_stage7_refusal_and_returns():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        promote = Mock(side_effect=cl.PromotionRefused("promotion refused for test"))
        with contextlib.redirect_stderr(io.StringIO()) as err:
            result = run_validation(team, row(), promote)
        promote.assert_called_once_with(team, C)
        assert result["commit"] == "0123456789abcdef"
        assert err.getvalue() == "Stage 7 refused at 0123456789: promotion refused for test\n"
        assert ": 5" not in err.getvalue()


def test_validate_run_logs_real_stage7_refusal_reason_once():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        with contextlib.redirect_stderr(io.StringIO()) as err:
            result = run_validation(team, row(), Mock(wraps=cl.stage7))
        assert result["commit"] == "0123456789abcdef"
        assert err.getvalue() == ("Stage 7 refused at 0123456789: "
                                  "0123456789abcdef has no passing Stage 6 validation; every test must pass\n")


def test_cmd_promote_reports_refusal_reason_once_with_exit_five():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        with contextlib.redirect_stderr(io.StringIO()) as err, patch.object(cl, "git") as git:
            try:
                cl.cmd_promote(team, SimpleNamespace(hash=C))
            except SystemExit as exc:
                assert exc.code == 5
            else:
                raise AssertionError("promote accepted an unvalidated commit")
        assert err.getvalue() == "0123456789abcdef has no passing Stage 6 validation; every test must pass\n"
        git.assert_not_called()


def test_stage7_review_finding_never_blocks_promotion():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); save_rows(team, [row()])
        save_finding(team, "feat", {"id": "feat#1", "state": "open", "severity": 2})
        with patch.object(cl, "git", side_effect=git_before_base) as git, patch.object(cl, "out", side_effect=fake_out), \
                patch.object(cl, "stamp_docs", return_value=None), contextlib.redirect_stdout(io.StringIO()):
            assert cl.stage7(team, C) == C
        assert any(call.args[1:2] == ("merge",) for call in git.call_args_list)


C0 = "1111111111111111111111111111111111111111"
H1 = "2222222222222222222222222222222222222222"
C2 = "3333333333333333333333333333333333333333"


def chain_ancestor(a, b):
    chain = [C0, H1, C, C2]
    return a in chain and b in chain and chain.index(a) <= chain.index(b)


def test_landed_hashes_includes_every_member_and_skips_promotions():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        (team.dir / "landed.log").write_text(
            json.dumps({"hash": H1, "wos": ["w1", "w-other"]}) + "\n" +
            json.dumps({"promote": C, "to": "main"}) + "\n" +
            json.dumps({"hash": C2, "wos": ["w2"]}) + "\n")
        assert cl.landed_hashes(team) == {"w1": H1, "w-other": H1, "w2": C2}


def test_closing_commit_prefers_fixed_by_landing():
    finding = {"fixed_by": "w2", "closed_at": C, "reason": "passes at M 0123456789"}
    assert cl.closing_commit(finding, {"w2": C2}) == C2
    assert cl.closing_commit(finding, {}) is None


def test_closing_commit_reads_recorded_commit():
    assert cl.closing_commit({"fixed_by": None, "closed_at": C}, {}) == C


def test_closing_commit_parses_legacy_validation_reason():
    assert cl.closing_commit({"reason": "passes in validation at C 0123456789"}, {}) == "0123456789"


def test_closing_commit_parses_legacy_recheck_reason():
    assert cl.closing_commit({"reason": "passes at M 0123456789"}, {}) == "0123456789"
    assert cl.closing_commit({"reason": "other"}, {}) is None


def test_unfixed_failures_stage5_fix_lands_after_candidate():
    finding = {"id": "feat#1", "state": "closed", "test": "a", "Ms": [H1], "wos": ["w1"], "fixed_by": "w2"}
    assert cl.unfixed_failures(C, [finding], {"w1": H1, "w2": C2}, chain_ancestor) == ["feat#1"]


def test_unfixed_failures_stage5_fix_in_candidate():
    finding = {"id": "feat#1", "state": "closed", "test": "a", "Ms": [H1], "wos": ["w1"], "fixed_by": "w2"}
    assert cl.unfixed_failures(C, [finding], {"w1": C0, "w2": H1}, chain_ancestor) == []


def test_unfixed_failures_test_failure_after_candidate():
    finding = {"id": "feat#1", "test": "a", "state": "closed", "Ms": [C2], "fixed_by": "w2"}
    assert cl.unfixed_failures(C, [finding], {"w2": C2}, chain_ancestor) == []


def test_unfixed_failures_validation_closed_by_candidate():
    finding = {"id": "validation#1", "state": "closed", "test": "a", "commits": [C0], "closed_at": C}
    assert cl.unfixed_failures(C, [finding], {}, chain_ancestor) == []


def test_unfixed_failures_validation_closed_later():
    finding = {"id": "validation#1", "state": "closed", "test": "a", "commits": [C0], "closed_at": C2}
    assert cl.unfixed_failures(C, [finding], {}, chain_ancestor) == ["validation#1"]


def test_unfixed_failures_recheck_closed_later():
    finding = {"id": "feat#2", "state": "closed", "test": "a", "Ms": [H1], "closed_at": C2}
    assert cl.unfixed_failures(C, [finding], {}, chain_ancestor) == ["feat#2"]


def test_unfixed_failures_excludes_open_dropped_and_without_defect_evidence():
    findings = [{"id": "open#1", "state": "open", "wos": ["w1"]},
                {"id": "drop#1", "state": "dropped", "wos": ["w1"]},
                {"id": "empty#1", "state": "closed"}]
    assert cl.unfixed_failures(C, findings, {"w1": H1}, chain_ancestor) == []


def test_unfixed_failures_unknown_fix_landing_blocks():
    finding = {"id": "feat#1", "test": "a", "Ms": [H1], "state": "closed", "wos": ["w1"], "fixed_by": "missing"}
    assert cl.unfixed_failures(C, [finding], {"w1": H1}, chain_ancestor) == ["feat#1"]


def test_unfixed_failures_review_without_test_evidence_does_not_block():
    finding = {"id": "feat#1", "state": "closed", "wos": ["missing"], "closed_at": C2}
    assert cl.unfixed_failures(C, [finding], {}, chain_ancestor) == []


def test_ancestry_git_error_refuses_promotion():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        with patch.object(cl, "git", return_value=SimpleNamespace(returncode=128)) as git:
            try:
                cl.ancestry(team)(C0, C)
            except cl.PromotionRefused as exc:
                assert C0 in str(exc) and C in str(exc)
            else:
                raise AssertionError("unknown ancestry accepted")
        git.assert_called_once_with(team.repo, "merge-base", "--is-ancestor", C0, C, check=False)


def test_ancestry_caches_yes_and_no():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        with patch.object(cl, "git", side_effect=[SimpleNamespace(returncode=0), SimpleNamespace(returncode=1)]) as git:
            ancestor = cl.ancestry(team)
            assert ancestor(C0, C) is True
            assert ancestor(C0, C) is True
            assert ancestor(C2, C) is False
            assert ancestor(C2, C) is False
        assert git.call_count == 2


def save_finding(team, feature, finding):
    (team.dir / "findings").mkdir(exist_ok=True)
    (team.dir / "findings" / f"{feature}.json").write_text(json.dumps([finding]))


def tick_out(repo, *args, **kwargs):
    if args[:1] == ("rev-list",):
        return C + "\n" + C0 + "\n"
    return fake_out(repo, *args, **kwargs)


def tick_git(repo, *args, **kwargs):
    if args[:2] == ("merge-base", "--is-ancestor"):
        a, b = args[-2:]
        if a == b: return SimpleNamespace(returncode=0, stdout="", stderr="")
        if b == "landing":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0 if chain_ancestor(a, b) else 1, stdout="", stderr="")
    return SimpleNamespace(returncode=0, stdout="", stderr="")


def run_real_tick(team, result, git):
    with patch.object(cl, "halted", return_value=False), \
            patch.object(cl, "drive_buildq_restart"), patch.object(cl, "runner_restart", return_value=False), \
            patch.object(cl, "alpha_cfg", return_value={"host": "fake", "path": "/fake", "suite": "suite"}), \
            patch.object(cl, "validate_due", return_value=True), patch.object(cl, "read_recheck", return_value=[]), \
            patch.object(cl, "out", side_effect=tick_out), \
            patch.object(cl, "check_at", return_value=result), patch.object(cl, "git", git), \
            patch.object(cl, "stamp_docs", return_value=None), \
            contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        cl.cmd_validate_run(team, SimpleNamespace(once=True))


def test_runner_validates_and_promotes_with_review_finding_open():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        save_finding(team, "feat", {"id": "feat#1", "state": "open", "wos": ["w1"]})
        (team.dir / "landed.log").write_text(json.dumps({"hash": H1, "wos": ["w1"]}) + "\n")
        git = Mock(side_effect=tick_git)
        run_real_tick(team, {"result": "pass", "time": "2026-01-01T00:00:00+00:00", "seconds": 1}, git)
        assert [r["commit"] for r in cl.validation_rows(team)] == [C]
        assert any(call.args[1:2] == ("merge",) for call in git.call_args_list)


def test_runner_closes_validation_finding_and_promotes_same_tick():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        save_finding(team, "validation", {"id": "validation#1", "by": "validation", "test": "a",
                                           "commits": [C0], "state": "open"})
        git = Mock(side_effect=tick_git)
        run_real_tick(team, {"result": "pass", "time": "2026-01-01T00:00:00+00:00", "seconds": 1}, git)
        finding = cl.find_finding(team, "validation#1")
        assert finding["state"] == "closed" and finding.get("closed_at") == C
        assert any(call.args[1:2] == ("merge",) and "--ff-only" in call.args and call.args[-1] == C
                   for call in git.call_args_list)


def test_runner_adds_failed_commit_to_existing_validation_finding():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        save_finding(team, "validation", {"id": "validation#1", "by": "validation", "test": "a",
                                           "commits": [C0], "state": "open"})
        git = Mock(side_effect=tick_git)
        run_real_tick(team, {"result": "fail", "tail": "FAILED ZONES: a",
                             "time": "2026-01-01T00:00:00+00:00", "seconds": 1}, git)
        findings = cl.load_findings(team, "validation")
        assert len(findings) == 1 and findings[0]["commits"] == [C0, C]
        assert not any(call.args[1:2] == ("merge",) for call in git.call_args_list)


def test_r24_hazard_refuses_old_commit_then_promotes_fixed_commit():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        save_rows(team, [row()])
        save_finding(team, "feat", {"id": "feat#1", "state": "closed", "test": "a", "Ms": [H1], "wos": ["w1"], "fixed_by": "w2"})
        (team.dir / "landed.log").write_text(json.dumps({"hash": H1, "wos": ["w1"]}) + "\n" +
                                               json.dumps({"hash": C2, "wos": ["w2"]}) + "\n")
        with patch.object(cl, "git", side_effect=tick_git) as git, patch.object(cl, "out", side_effect=fake_out), \
                patch.object(cl, "stamp_docs", return_value=None), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            try:
                cl.stage7(team, C)
            except cl.PromotionRefused as exc:
                assert "test failures not fixed at or before" in str(exc) and "feat#1" in str(exc)
            else:
                raise AssertionError("Stage 7 promoted a commit predating its fix")
            assert not any(call.args[1:2] == ("merge",) for call in git.call_args_list)
            try:
                cl.cmd_promote(team, SimpleNamespace(hash=None))
            except SystemExit as exc:
                assert exc.code != 0
            else:
                raise AssertionError("promote accepted a commit predating its fix")
            assert not any(call.args[1:2] == ("merge",) for call in git.call_args_list)
            save_rows(team, [row(), row(commit=C2)])
            cl.cmd_promote(team, SimpleNamespace(hash=None))
            assert any(call.args[1:2] == ("merge",) and call.args[-1] == C2 for call in git.call_args_list)


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
