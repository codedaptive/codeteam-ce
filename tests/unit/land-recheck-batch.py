#!/usr/bin/env -S python3 -u
"""Stage 5 batching with git, processes, notifications and team boundaries faked."""
import contextlib
import fcntl
import importlib.machinery
import importlib.util
import json
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_batch", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)

ROWS = [
    {"time": "t0", "M": "done", "wo": "done", "zones": ["D"], "overlapping": [], "done": "old"},
    {"time": "t1", "M": "aaaaaaaaaaaa", "wo": "one", "zones": ["A"], "overlapping": ["prior-a"],
     "files": ["a", "shared"], "set": ["one", "member"]},
    {"time": "t2", "M": "bbbbbbbbbbbb", "wo": "two", "zones": ["B"], "overlapping": ["prior-b"],
     "files": ["shared", "b"]},
    {"time": "tx", "M": "unrelated", "wo": "wait", "zones": ["X"], "overlapping": [], "files": ["x"]},
    {"time": "t3", "M": "cccccccccccc", "wo": "three", "zones": ["C"], "overlapping": ["prior-c"], "files": ["c"]},
]


def setup(root):
    team = SimpleNamespace(dir=root, repo=root / "repo", manifest="team.toml", landing="landing",
                           notify=Mock(), log=Mock(), c=lambda key, default: "Orchestrator")
    (root / "recheck.jsonl").write_text("".join(json.dumps(row) + "\n" for row in ROWS))
    return team


def git(repo, *args, **kwargs):
    assert repo == team_repo[0]
    assert args[:2] == ("merge-base", "--is-ancestor")
    return SimpleNamespace(returncode=0 if args[2:] in (("aaaaaaaaaaaa", "cccccccccccc"),
                                                          ("bbbbbbbbbbbb", "cccccccccccc")) else 1)


team_repo = []


@contextlib.contextmanager
def environment(team):
    team_repo[:] = [team.repo]
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(cl, "halted", return_value=False))
        stack.enter_context(patch.object(cl, "runner_unmoved", return_value=False))
        stack.enter_context(patch.object(cl, "git", side_effect=git))
        stack.enter_context(patch.object(cl, "Lock", return_value=contextlib.nullcontext()))
        stack.enter_context(patch.object(cl, "FindingsLock", return_value=contextlib.nullcontext()))
        stack.enter_context(patch.object(cl, "landed_rec", side_effect=lambda t, w: {
            "wo": w, "zone": {"one": "A", "member": "A", "two": "B", "three": "C"}[w], "feature": w}))
        stack.enter_context(patch.object(cl, "now", return_value="finished"))
        yield stack


def selected(team):
    result = cl.recheck_ready(team)
    assert result == [ROWS[1], ROWS[2], ROWS[4]], f"expected three ancestors, got {result!r}"
    return result


def test_ready_batches_ancestors_and_leaves_unrelated_pending():
    with tempfile.TemporaryDirectory() as tmp:
        team = setup(Path(tmp))
        with environment(team):
            selected(team)


def test_ready_returns_none_when_nothing_is_pending():
    with tempfile.TemporaryDirectory() as tmp:
        team = setup(Path(tmp))
        (team.dir / "recheck.jsonl").write_text(json.dumps(ROWS[0]) + "\n")
        with environment(team):
            assert cl.recheck_ready(team) is None


def test_ready_takes_move_first():
    with tempfile.TemporaryDirectory() as tmp:
        team = setup(Path(tmp))
        move = {"time": "tm", "M": "move", "wo": "move", "zones": [], "overlapping": [], "move": True}
        with (team.dir / "recheck.jsonl").open("a") as stream:
            stream.write(json.dumps(move) + "\n")
        with environment(team):
            assert cl.recheck_ready(team) == [move]


def test_one_recheck_union_result_completion_without_slow_flag_report():
    with tempfile.TemporaryDirectory() as tmp:
        team = setup(Path(tmp))
        with environment(team) as stack:
            stored = cl.read_recheck(team)
            rows = [stored[1], stored[2], stored[4]]
            stack.enter_context(patch.object(cl, "itest_checkout", return_value=team.dir / "itest"))
            stack.enter_context(patch.object(cl, "recheck_steps", return_value=([], [])))
            stack.enter_context(patch.object(cl, "team_env", return_value={}))
            stack.enter_context(patch.object(cl, "step_results", return_value=[]))
            stack.enter_context(patch.object(cl, "keep_recheck_logs"))
            recheck = stack.enter_context(patch.object(cl, "recheck_result", wraps=cl.recheck_result))
            after = stack.enter_context(patch.object(cl, "after_landing"))
            slow = stack.enter_context(patch.object(cl, "report_slow_tests"))
            stack.enter_context(patch.object(cl, "apply_recheck_findings"))
            cl.recheck_one(team, rows)
        recheck.assert_called_once()
        union = recheck.call_args.args[2]
        assert union["zones"] == ["A", "B", "C"]
        assert union["files"] == ["a", "shared", "b", "c"]
        assert union["M"] == "cccccccccccc"
        [record] = [json.loads(line) for line in (team.dir / "integration-results.jsonl").read_text().splitlines()]
        assert record["batch"] == ["one", "two", "three"]
        assert record["M"] == "cccccccccccc" and record["zones"] == ["A", "B", "C"]
        saved = cl.read_recheck(team)
        assert [saved[i].get("done") for i in (1, 2, 4)] == ["finished", "finished", "finished"]
        assert "done" not in saved[3]
        assert [[r["wo"] for r in c.args[1]] for c in after.call_args_list] == [["one", "member"], ["two"], ["three"]]
        slow.assert_not_called()


def test_slow_batch_reports_only_slow_stage2_source_and_files():
    with tempfile.TemporaryDirectory() as tmp:
        team = setup(Path(tmp))
        with environment(team) as stack:
            rows = [cl.read_recheck(team)[i] for i in (1, 2, 4)]
            records = {"one": {"zone": "A", "stage2_tests_s": 1000, "files": ["a", "shared"]},
                       "two": {"zone": "B", "stage2_tests_s": 100, "files": ["b"]},
                       "three": {"zone": "C"}}
            stack.enter_context(patch.object(cl, "landed_rec", side_effect=lambda team, wo: records.get(wo, {})))
            stack.enter_context(patch.object(cl, "itest_checkout", return_value=team.dir / "itest"))
            flag = {"total_s": 960.0}
            stack.enter_context(patch.object(cl, "recheck_result", return_value={
                "time": "finished", "M": "cccccccccccc", "tests": [], "slow_tests": flag}))
            slow = stack.enter_context(patch.object(cl, "report_slow_tests"))
            stack.enter_context(patch.object(cl, "apply_recheck_findings"))
            stack.enter_context(patch.object(cl, "after_landing"))
            cl.recheck_one(team, rows)
        slow.assert_called_once_with(team, flag, "one, two, three recheck at M cccccccccc", "Stage 5",
            {"wo": "one", "zone": "A", "stage": 5, "commit": "cccccccccccc"}, ["a", "shared"])


def test_checkout_failure_keeps_batch_pending_and_notifies_once():
    with tempfile.TemporaryDirectory() as tmp:
        team = setup(Path(tmp))
        with environment(team) as stack:
            stored = cl.read_recheck(team)
            rows = [stored[1], stored[2], stored[4]]
            stack.enter_context(patch.object(cl, "itest_checkout", side_effect=cl.CheckoutFailed("cccccccccccc", "bad checkout")))
            cl.recheck_one(team, rows)
            saved = cl.read_recheck(team)
            assert all("done" not in saved[i] for i in (1, 2, 4))
            assert "checkout_failed" not in saved[1] and "checkout_failed" not in saved[2]
            assert saved[4]["checkout_failed"] == "finished"
            cl.recheck_one(team, [saved[1], saved[2], saved[4]])
        team.notify.assert_called_once()
        assert all(wo in team.notify.call_args.args[2] for wo in ("one", "two", "three"))


def test_checkout_and_result_hold_the_itest_lock():
    with tempfile.TemporaryDirectory() as tmp:
        team = setup(Path(tmp))
        checks = []
        def locked(*args):
            with (team.dir / "itest.lock").open("r+") as other:
                try:
                    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    checks.append(True)
                else:
                    checks.append(False)
                    fcntl.flock(other, fcntl.LOCK_UN)
        def checkout(*args):
            locked()
            return team.dir / "itest"
        def result(*args):
            locked()
            return {"time": "finished", "M": "cccccccccccc", "wo": "three", "zones": ["A", "B", "C"],
                    "overlapping": [], "tests": []}
        with environment(team) as stack:
            stored = cl.read_recheck(team)
            rows = [stored[1], stored[2], stored[4]]
            stack.enter_context(patch.object(cl, "itest_checkout", side_effect=checkout))
            stack.enter_context(patch.object(cl, "recheck_result", side_effect=result))
            stack.enter_context(patch.object(cl, "report_slow_tests"))
            stack.enter_context(patch.object(cl, "apply_recheck_findings"))
            stack.enter_context(patch.object(cl, "after_landing"))
            cl.recheck_one(team, rows)
        assert checks == [True, True]


def run_failure(name, owner, zone, overlapping):
    with tempfile.TemporaryDirectory() as tmp:
        team = setup(Path(tmp))
        (team.dir / "findings").mkdir()
        with environment(team) as stack:
            stored = cl.read_recheck(team)
            rows = [stored[1], stored[2], stored[4]]
            stack.enter_context(patch.object(cl, "itest_checkout", return_value=team.dir / "itest"))
            stack.enter_context(patch.object(cl, "recheck_result", return_value={
                "time": "finished", "M": "cccccccccccc", "wo": "three", "zones": ["A", "B", "C"],
                "overlapping": ["prior-a", "prior-b", "prior-c"], "tests": [{"name": name, "result": "fail"}]}))
            stack.enter_context(patch.object(cl, "report_slow_tests"))
            stack.enter_context(patch.object(cl, "after_landing"))
            cl.recheck_one(team, rows)
        findings = list(cl.all_findings(team))
        assert len(findings) == 1
        finding = findings[0]
        assert finding["wos"] == [owner, overlapping]
        assert finding["zone"] == zone
        assert finding["Ms"] == ["cccccccccccc"]
        assert "at M cccccccccc" in finding["what"]
        assert finding["state"] == "open" and finding["kind"] == "test"


def test_failing_zone_is_attributed_to_middle_row():
    run_failure("tests B (src/b)", "two", "B", "prior-b")


def test_failing_compile_is_attributed_to_middle_row():
    run_failure("compile B (src/b)", "two", "B", "prior-b")


def test_failing_rit_is_attributed_to_middle_row():
    run_failure("rits B (src/b)", "two", "B", "prior-b")


def test_unknown_step_is_attributed_to_newest_row():
    run_failure("type check", "three", "C", "prior-c")


def test_unreached_zone_is_attributed_to_newest_row():
    run_failure("rits Z (src/z)", "three", "C", "prior-c")


def existing_finding_after_batch(result, commits):
    with tempfile.TemporaryDirectory() as tmp:
        team = setup(Path(tmp))
        (team.dir / "findings").mkdir()
        finding = {"id": "existing#1", "state": "open", "by": "recheck", "kind": "test",
                   "test": "tests B (src/b)", "Ms": commits}
        cl.save_findings(team, "existing", [finding])
        with environment(team) as stack:
            stored = cl.read_recheck(team)
            rows = [stored[1], stored[2], stored[4]]
            stack.enter_context(patch.object(cl, "itest_checkout", return_value=team.dir / "itest"))
            stack.enter_context(patch.object(cl, "recheck_result", return_value={
                "time": "finished", "M": "cccccccccccc", "wo": "three", "zones": ["A", "B", "C"],
                "overlapping": ["prior-a", "prior-b", "prior-c"],
                "tests": [{"name": "tests B (src/b)", "result": result}]}))
            stack.enter_context(patch.object(cl, "report_slow_tests"))
            stack.enter_context(patch.object(cl, "after_landing"))
            cl.recheck_one(team, rows)
        findings = list(cl.all_findings(team))
        assert len(findings) == 1
        team.notify.assert_not_called()
        return findings[0]


def test_existing_failure_gets_batch_commit_added_once():
    finding = existing_finding_after_batch("fail", ["old"])
    assert finding["Ms"] == ["old", "cccccccccccc"]
    assert finding["state"] == "open"


def test_existing_failure_does_not_duplicate_batch_commit():
    finding = existing_finding_after_batch("fail", ["old", "cccccccccccc"])
    assert finding["Ms"] == ["old", "cccccccccccc"]
    assert finding["state"] == "open"


def test_passing_step_closes_existing_finding_at_batch_commit():
    finding = existing_finding_after_batch("pass", ["old"])
    assert finding["state"] == "closed"
    assert finding["closed_at"] == "cccccccccccc"
    assert finding["closed"] == "finished"


if __name__ == "__main__":
    failures = 0
    for name, test in list(globals().items()):
        if name.startswith("test_") and callable(test):
            try:
                test()
                print(f"PASS {name}")
            except Exception:
                failures += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    print(f"{failures} failed")
    sys.exit(bool(failures))
