#!/usr/bin/env -S python3 -u
"""Isolated Stage 7 promotion and validation hand-off contracts: the unit tests (rule 11); git, where called,
is faked. The tests that go through stage7, cmd_promote or the validation runner, which take the real landing Lock (the
runner also its validate-run flock), are in tests/integration/land-v52-promote.py."""
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
