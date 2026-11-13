#!/usr/bin/env -S python3 -u
"""Unit contracts for checkout failures, land-check freshness and nested verdicts."""
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

# Restart markers and stage admissions live beside the queue; keep them out of the checkout.
os.environ["CODETEAM_QUEUE_DIR"] = str(Path(tempfile.mkdtemp(prefix="land-queue-")) / "queue")

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_fixes", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)

# These isolated stage fixtures represent teams that have already moved over.
cl.v54_unmoved = Mock(return_value=False)


def make_team(root):
    repo = root / "repo"
    repo.mkdir()
    manifest = root / "sample.toml"
    manifest.write_text(f'repo = "{repo}"\nworktree_root = "{root / "team"}"\n'
                        '[land]\norchestrator = "Skippy"\n')
    team = cl.Team(str(manifest))
    team.notify = Mock()
    return team


HUNG = "zone-test: HUNG: no output for 1 s; stopped the run and every process under it"
PASS = "zone-test: PASS (exit 0); record /r.json"
FAIL = "zone-test: FAIL (exit 1); record /r.json"


def test_nested_hung_followed_by_pass():
    with patch.object(cl, "records_pass", return_value=False):
        assert cl.step_outcome(0, HUNG + "\n" + PASS) == "PASS"


def test_nested_hung_followed_by_fail():
    with patch.object(cl, "records_pass", return_value=False):
        assert cl.step_outcome(1, HUNG + "\n" + FAIL) == "FAIL"


def test_nested_hung_followed_by_broken():
    with patch.object(cl, "records_pass", return_value=False):
        assert cl.step_outcome(1, HUNG + "\nzone-test: BROKEN (exit 1); record /r.json") == "FAIL"


def test_brokenish_is_not_a_broken_verdict():
    with patch.object(cl, "records_pass", return_value=False):
        assert cl.step_outcome(1, HUNG + "\nzone-test: BROKENISH") == "HUNG"


def test_pass_followed_by_hung():
    with patch.object(cl, "records_pass", return_value=False):
        assert cl.step_outcome(1, PASS + "\n" + HUNG) == "HUNG"


def test_exit_124_without_marker_is_hung():
    with patch.object(cl, "records_pass", return_value=False):
        assert cl.step_outcome(124, "no marker") == "HUNG"


def test_exit_124_overrides_later_pass():
    with patch.object(cl, "records_pass", return_value=True):
        assert cl.step_outcome(124, HUNG + "\n" + PASS) == "HUNG"


def test_parenthesized_hung_verdict():
    with patch.object(cl, "records_pass", return_value=False):
        assert cl.step_outcome(0, "zone-test: HUNG (exit 124); record /r.json") == "HUNG"


def test_password_is_not_a_pass_verdict():
    with patch.object(cl, "records_pass", return_value=False):
        assert cl.step_outcome(0, HUNG + "\nzone-test: PASSWORD") == "HUNG"


def test_checkout_retries_forced_without_clean():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        tree = team.dir / "itest"
        tree.mkdir()
        replies = [SimpleNamespace(returncode=1, stderr="error: Your local changes ..."),
                   SimpleNamespace(returncode=0, stderr="")]
        with patch.object(cl, "git", side_effect=replies) as git:
            assert cl.itest_checkout(team, "merge1") == tree
        assert git.call_args_list == [call(tree, "checkout", "-q", "--detach", "merge1", check=False),
                                      call(tree, "checkout", "-q", "-f", "--detach", "merge1", check=False)]
        assert all("clean" not in c.args for c in git.call_args_list)


def test_checkout_both_fail_reports_second_stderr_without_clean():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        (team.dir / "itest").mkdir()
        replies = [SimpleNamespace(returncode=1, stderr="first"), SimpleNamespace(returncode=1, stderr=" second error \n")]
        with patch.object(cl, "git", side_effect=replies) as git:
            try:
                cl.itest_checkout(team, "merge2")
            except Exception as exc:
                assert isinstance(exc, cl.CheckoutFailed)
                assert (exc.M, exc.error) == ("merge2", "second error")
            else:
                raise AssertionError("checkout did not fail")
        assert git.call_args_list == [call(team.dir / "itest", "checkout", "-q", "--detach", "merge2", check=False),
                                      call(team.dir / "itest", "checkout", "-q", "-f", "--detach", "merge2", check=False)]
        assert all("clean" not in c.args for c in git.call_args_list)


def test_missing_checkout_failure_reports_git_error():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        with patch.object(cl, "git", return_value=SimpleNamespace(returncode=1, stderr=" add failed \n")) as git:
            try:
                cl.itest_checkout(team, "merge3")
            except Exception as exc:
                assert isinstance(exc, cl.CheckoutFailed)
                assert (exc.M, exc.error) == ("merge3", "add failed")
            else:
                raise AssertionError("worktree add did not fail")
        git.assert_called_once_with(team.repo, "worktree", "add", "--detach", str(team.dir / "itest"), "merge3", check=False)


def test_runner_keeps_a_failed_checkout_pending_and_retries_it():
    # A recheck that ran nothing is not done. Its row stays pending, the failure is recorded
    # and told once, and the next poll tries the same row again; the rows after it wait their turn.
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        rows = [{"M": "first123456789", "wo": "one", "zones": ["A"], "overlapping": []},
                {"M": "second12345678", "wo": "two", "zones": ["A"], "overlapping": []}]
        for wo in ("one", "two"):
            (team.dir / "wo" / f"{wo}.landed.json").write_text(json.dumps({"wo": wo, "zone": "A"}))
        (team.dir / "recheck.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
        failed, worked = SimpleNamespace(returncode=1, stderr="failed"), SimpleNamespace(returncode=0, stderr="")
        results = team.dir / "integration-results.jsonl"
        with patch.object(cl, "git", side_effect=[failed, failed, worked, worked]) as git, \
                patch.object(cl, "halted", return_value=False), patch.object(cl.codeteam_tm, "exclude"), \
                patch.object(cl, "recheck_steps", return_value=([], [])), patch.object(cl, "step_results", return_value=[]), \
                patch.object(cl, "apply_recheck_findings"), patch.object(cl, "after_landing"), \
                patch.object(cl, "now", return_value="now"):
            cl.cmd_recheck_run(team, SimpleNamespace(once=True))
            assert cl.read_recheck(team) == [{**rows[0], "checkout_failed": "now"}, rows[1]]
            assert [json.loads(line).get("checkout") for line in results.read_text().splitlines()] == ["failed"]
            assert team.notify.call_count == 1
            assert "stays pending" in team.notify.call_args.args[2]
            cl.cmd_recheck_run(team, SimpleNamespace(once=True))          # still failing: no new row, no new notice
            assert cl.read_recheck(team) == [{**rows[0], "checkout_failed": "now"}, rows[1]]
            assert len(results.read_text().splitlines()) == 1 and team.notify.call_count == 1
            assert git.call_args_list[1].args[-1] == "first123456789"      # the same row was tried again
            cl.cmd_recheck_run(team, SimpleNamespace(once=True))          # the checkout works: the row completes
            assert cl.read_recheck(team) == [{**rows[0], "checkout_failed": "now", "done": "now"}, rows[1]]
            cl.cmd_recheck_run(team, SimpleNamespace(once=True))
        assert cl.read_recheck(team) == [{**rows[0], "checkout_failed": "now", "done": "now"}, {**rows[1], "done": "now"}]
        assert [json.loads(line).get("checkout") for line in results.read_text().splitlines()] == ["failed", None, None]


def test_a_missing_but_registered_itest_tree_is_added_again_with_force():
    # land/itest was once deleted while git still listed it, so every `worktree add` failed.
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        tree = team.dir / "itest"
        stale = SimpleNamespace(returncode=128, stderr=f"fatal: '{tree}' is a missing but already registered worktree;\n"
                                                       "use 'add -f' to override, or 'prune' or 'remove' to clear\n")
        with patch.object(cl, "git", side_effect=[stale, SimpleNamespace(returncode=0, stderr="")]) as git, \
                patch.object(cl.codeteam_tm, "exclude") as exclude:
            assert cl.itest_checkout(team, "merge4") == tree
        assert git.call_args_list == [call(team.repo, "worktree", "add", "--detach", str(tree), "merge4", check=False),
                                      call(team.repo, "worktree", "add", "-f", "--detach", str(tree), "merge4", check=False)]
        exclude.assert_called_once_with([tree])


def test_run_recheck_tick_returns_none_after_a_failed_checkout():
    # The runner sleeps a poll only when the tick returns None; a pending row that returned a job would spin.
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        row = {"M": "first123456789", "wo": "one", "zones": ["A"], "overlapping": []}
        with patch.object(cl, "recheck_one", return_value={"checkout": "failed"}):
            assert cl.run_recheck_tick(team, row) is None
        with patch.object(cl, "recheck_one", return_value={"tests": []}):
            assert cl.run_recheck_tick(team, row) is not None


def test_land_check_digest_is_sha256_of_script():
    assert cl.land_check_digest() == hashlib.sha256(cl.REMOTE_CHECK.encode()).hexdigest()


def test_installed_local_digest_and_missing():
    with tempfile.TemporaryDirectory() as tmp:
        a = {"local": True, "path": tmp}
        assert cl.installed_land_check_digest(a) == ""
        (Path(tmp) / ".git").mkdir()
        (Path(tmp) / ".git" / "land-check").write_bytes(b"old")
        assert cl.installed_land_check_digest(a) == "cba06b5736faf67e54b07b561eae94395e774c517a7d910a54369e1263ccfbd4"


def test_remote_digest_uses_single_ssh_and_strips_output():
    a = {"host": "alpha", "path": "clone"}
    with patch.object(cl, "ssh", return_value=SimpleNamespace(stdout=" digest \n")) as ssh:
        assert cl.installed_land_check_digest(a) == "digest"
    ssh.assert_called_once_with(a, "shasum -a 256 ~/bin/land-check 2>/dev/null | cut -c1-64", timeout=60)


def test_stale_local_script_is_reinstalled():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = make_team(root)
        clone = root / "clone"
        (clone / ".git").mkdir(parents=True)
        script = clone / ".git" / "land-check"
        script.write_text('#!/bin/sh\nh=$1; suite=$2; timeout=$3; fp=$4; want=$5\n')
        with patch.object(cl, "git") as git:
            assert cl.ensure_land_check(team, {"local": True, "path": str(clone)}) is None
        assert script.read_text() == cl.REMOTE_CHECK
        git.assert_not_called()


def test_current_local_script_does_not_install():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = make_team(root)
        clone = root / "clone"
        (clone / ".git").mkdir(parents=True)
        (clone / ".git" / "land-check").write_text(cl.REMOTE_CHECK)
        with patch.object(cl, "install_land_check", create=True) as install:
            assert cl.ensure_land_check(team, {"local": True, "path": str(clone)}) is None
        install.assert_not_called()


def test_digest_read_error_triggers_install():
    team, a = Mock(), {"local": True, "path": "clone"}
    with patch.object(cl, "installed_land_check_digest", side_effect=OSError("read failed"), create=True), \
            patch.object(cl, "install_land_check", return_value=None, create=True) as install:
        assert cl.ensure_land_check(team, a) is None
    install.assert_called_once_with(team, a)


def test_stale_install_error_explains_recovery():
    team, a = Mock(), {"local": True, "path": "clone"}
    with patch.object(cl, "installed_land_check_digest", return_value="", create=True), \
            patch.object(cl, "install_land_check", return_value="write denied", create=True):
        detail = cl.ensure_land_check(team, a)
    assert all(s in detail for s in ("stale", "write denied", "alpha-install"))


def test_local_stale_install_failure_never_runs_script():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        a = {"local": True, "host": "local", "path": str(Path(tmp) / "clone"), "suite": "tests"}
        with patch.object(cl, "git", return_value=SimpleNamespace(returncode=0)), \
                patch.object(cl, "HERE", Path(tmp) / "bin"), \
                patch.object(cl, "ensure_land_check", return_value="stale: write denied; alpha-install", create=True), \
                patch.object(cl.subprocess, "run") as run, patch.object(cl, "now", return_value="now"):
            result = cl.check_at(team, a, "hash", "validation")
        assert result == {"hash": "hash", "result": "toolchain", "detail": "stale: write denied; alpha-install", "time": "now"}
        assert not (team.dir / "results.jsonl").exists()
        run.assert_not_called()


def test_missing_local_clone_is_made_before_the_push():
    # Only install_land_check made a local tier's clone, so pushing to a missing one
    # failed every validate-run and the clone was never made.
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        a = {"local": True, "host": "local", "path": str(Path(tmp) / "clone"), "suite": "tests"}
        order = Mock()
        order.ensure.return_value = None
        order.git.return_value = SimpleNamespace(returncode=0, stderr="")
        order.run.return_value = {"hash": "hash", "result": "pass"}
        with patch.object(cl, "ensure_land_check", order.ensure), patch.object(cl, "git", order.git), \
                patch.object(cl, "run_land_check", order.run), patch.object(cl, "now", return_value="now"):
            result = cl.check_at(team, a, "hash", "validation")
        assert result == {"hash": "hash", "result": "pass", "time": "now"}
        names = [c[0] for c in order.mock_calls if c[0] in ("ensure", "git", "run")]
        assert names[:2] == ["ensure", "git"] and names[-1] == "run", names
        assert "push" in order.git.call_args.args


def test_missing_local_clone_install_failure_is_toolchain_without_a_push():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        a = {"local": True, "host": "local", "path": str(Path(tmp) / "clone"), "suite": "tests"}
        with patch.object(cl, "ensure_land_check", return_value="stale: clone failed; alpha-install"), \
                patch.object(cl, "git") as git, patch.object(cl, "run_land_check") as run, \
                patch.object(cl, "now", return_value="now"):
            result = cl.check_at(team, a, "hash", "validation")
        assert result == {"hash": "hash", "result": "toolchain", "detail": "stale: clone failed; alpha-install",
                          "time": "now"}
        git.assert_not_called()
        run.assert_not_called()


def test_existing_local_clone_is_pushed_before_the_freshness_check():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        clone = Path(tmp) / "clone"
        (clone / ".git").mkdir(parents=True)
        a = {"local": True, "host": "local", "path": str(clone), "suite": "tests"}
        order = Mock()
        order.ensure.return_value = None
        order.git.return_value = SimpleNamespace(returncode=0, stderr="")
        order.run.return_value = {"hash": "hash", "result": "pass"}
        with patch.object(cl, "ensure_land_check", order.ensure), patch.object(cl, "git", order.git), \
                patch.object(cl, "run_land_check", order.run), patch.object(cl, "now", return_value="now"):
            cl.check_at(team, a, "hash", "validation")
        assert [c[0] for c in order.mock_calls if c[0] in ("ensure", "git", "run")] == ["git", "ensure", "run"]


def test_current_remote_digest_before_run_does_not_install():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        a = {"host": "alpha", "path": "clone", "suite": "tests", "toolchain": ["echo toolchain"]}
        digest = hashlib.sha256(cl.REMOTE_CHECK.encode()).hexdigest()
        replies = [SimpleNamespace(stdout=digest + "\n", returncode=0, stderr=""),
                   SimpleNamespace(stdout='{"hash":"hash","result":"pass"}', returncode=0, stderr="")]
        with patch.object(cl, "git", return_value=SimpleNamespace(returncode=0)), \
                patch.object(cl, "toolchain_fp", return_value="fp"), \
                patch.object(cl, "install_land_check", create=True) as install, \
                patch.object(cl, "ssh", side_effect=replies) as ssh:
            result = cl.check_at(team, a, "hash", "validation")
        assert result["result"] == "pass"
        install.assert_not_called()
        assert ssh.call_args_list[0] == call(a, "shasum -a 256 ~/bin/land-check 2>/dev/null | cut -c1-64", timeout=60)
        assert len(ssh.call_args_list) == 2
        assert "land-check hash" in ssh.call_args_list[1].args[1]


def test_remote_stale_install_success_runs_current_script():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        a = {"host": "alpha", "path": "clone", "suite": "tests", "toolchain": ["echo toolchain"]}
        replies = [SimpleNamespace(stdout="old\n", returncode=0, stderr=""),
                   SimpleNamespace(stdout=".git\n", returncode=0, stderr=""),
                   SimpleNamespace(stdout="", returncode=0, stderr=""),
                   SimpleNamespace(stdout='{"hash":"hash","result":"pass"}', returncode=0, stderr="")]
        with patch.object(cl, "git", return_value=SimpleNamespace(returncode=0)), \
                patch.object(cl, "toolchain_fp", return_value="fp"), \
                patch.object(cl, "ssh", side_effect=replies) as ssh:
            result = cl.check_at(team, a, "hash", "validation")
        assert result["result"] == "pass"
        assert len(ssh.call_args_list) == 4
        assert "cat > ~/bin/land-check.new" in ssh.call_args_list[1].args[1]
        assert ssh.call_args_list[1].kwargs == {"timeout": 60, "input": cl.REMOTE_CHECK}
        assert "~/bin/land-check hash" in ssh.call_args_list[-1].args[1]


def test_remote_stale_install_failure_records_toolchain_without_running():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        a = {"host": "alpha", "path": "clone", "suite": "tests", "toolchain": ["echo toolchain"]}
        replies = [SimpleNamespace(stdout="old\n", returncode=0, stderr=""),
                   SimpleNamespace(stdout="", returncode=255, stderr="ssh: connect to host alpha port 22: No route to host")]
        with patch.object(cl, "git", return_value=SimpleNamespace(returncode=0)), \
                patch.object(cl, "ssh", side_effect=replies) as ssh, patch.object(cl, "now", return_value="now"):
            result = cl.check_at(team, a, "hash", "validation")
        assert result["hash"] == "hash" and result["result"] == "toolchain" and result["time"] == "now"
        assert all(s in result["detail"] for s in ("stale", "No route to host", "alpha-install"))
        assert not (team.dir / "results.jsonl").exists()
        assert all("land-check hash" not in c.args[1] for c in ssh.call_args_list)


def test_install_timeout_returns_error():
    a = {"host": "alpha", "path": "clone"}
    with patch.object(cl, "ssh", side_effect=subprocess.TimeoutExpired("ssh", 60)):
        error = cl.install_land_check(Mock(), a)
    assert isinstance(error, str) and error and ("60" in error or "timeout" in error.lower() or "timed out" in error.lower())


def test_alpha_install_reports_install_error():
    team = Mock()
    a = {"host": "alpha", "path": "clone", "suite": "tests"}
    with patch.object(cl, "alpha_cfg", return_value=a), \
            patch.object(cl, "install_land_check", return_value="install broke", create=True), \
            patch.object(cl, "die", side_effect=SystemExit(5)) as die:
        try:
            cl.cmd_alpha_install(team, SimpleNamespace())
        except SystemExit:
            pass
        else:
            raise AssertionError("failed install did not terminate")
    assert die.call_args.args[0].startswith("alpha-install failed: ")
    assert "install broke" in die.call_args.args[0]


failed = 0
for test in [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)
             and (len(sys.argv) == 1 or k in sys.argv[1:])]:
    try:
        test()
        print(f"  PASS {test.__name__}")
    except (Exception, SystemExit) as exc:
        failed += 1
        print(f"  FAIL {test.__name__}: {type(exc).__name__}: {exc}")
print(f"{failed} failed" if failed else "all passed")
sys.exit(1 if failed else 0)
