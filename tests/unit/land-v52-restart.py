#!/usr/bin/env -S python3 -u
"""Stage 7 restart contracts with scratch manifests and fake processes, including the run-time parser: the unit tests
(rule 11). The tests through stage7's real landing Lock, after_promote's build-queue restart lock and the runners'
real locks are in tests/integration/land-v52-restart.py."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

# Restart markers and stage admissions live beside the queue; keep them out of the checkout.
os.environ["CODETEAM_QUEUE_DIR"] = str(Path(tempfile.mkdtemp(prefix="land-queue-")) / "queue")

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_restart", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", stderr="", returncode=0)):
    loader.exec_module(cl)

# These isolated stage fixtures represent teams that have already moved over.
cl.v54_unmoved = Mock(return_value=False)

OLD = "aaaaaaaaaaaaaaaaaaaa"
TIP = "0123456789abcdef0123"


def team_at(root, name="sample", land=True, tools=True):
    """A team whose repo is root/repo: a checkout of codeteam's tools (bin/codeteam-land), or with tools=False a
    product's repo."""
    teams = root / "teams"
    teams.mkdir(parents=True, exist_ok=True)
    repo = root / "repo"
    (repo / "bin").mkdir(parents=True, exist_ok=True)
    if tools:
        (repo / "bin" / "codeteam-land").touch()
    manifest = teams / f"{name}.toml"
    manifest.write_text(f'repo = "{repo}"\nworktree_root = "{root / name}"\n'
                        + ('[land]\norchestrator = "Skippy"\n' if land else ''))
    team = cl.Team(str(manifest))
    team.notify = Mock()
    return team


def marker(team, command, requested_ts=101):
    path = team.dir / "restart" / f"{command}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"requested": "2026-11-10T00:00:00+00:00", "requested_ts": requested_ts, "tip": TIP}))
    return path


def jobs_of(*teams, commands=("queue-run", "recheck-run", "validate-run")):
    """A fake codeteam_runner_jobs.runner_jobs naming these teams' runners (the module's own unit test is
    tests/unit/test_codeteam_runner_jobs.py; the real join is zone/tests/integration/test_promote_restarts.py)."""
    return Mock(return_value=[(team.manifest, command) for team in teams for command in commands])


def markers(team):
    return sorted(path.name for path in (team.dir / "restart").glob("*.json"))


def targets(path, expected):
    assert cl.restart_targets([path]) == expected


def test_targets_codeteam2():
    targets("v2/codeteam2/x.py", {"loops": True, "runners": False, "buildq": False})


def test_targets_v2_bin():
    targets("v2/bin/codeteam2", {"loops": True, "runners": False, "buildq": False})


def test_targets_v1_cli():
    targets("bin/codeteam", {"loops": True, "runners": False, "buildq": False})


def test_targets_detached_wo_branches():
    targets("share/codeteam_detached_wo_branches.py", {"loops": True, "runners": False, "buildq": False})


def test_targets_v2_tests():
    targets("v2/tests/x.py", {"loops": False, "runners": False, "buildq": False})


def test_targets_decisions():
    targets("v2/DECISIONS.md", {"loops": False, "runners": False, "buildq": False})


def test_targets_landing_program():
    targets("bin/codeteam-land", {"loops": False, "runners": True, "buildq": False})


def test_targets_ran_parser():
    targets("share/codeteam_ran.py", {"loops": False, "runners": True, "buildq": False})


def test_targets_lock_reach():
    targets("share/codeteam_lock_reach.py", {"loops": False, "runners": True, "buildq": False})


def test_targets_cargo_folders():
    targets("share/codeteam_cargo_folders.py", {"loops": False, "runners": True, "buildq": False})


def test_targets_unscoped_reach():
    targets("share/codeteam_unscoped_reach.py", {"loops": False, "runners": True, "buildq": False})


def test_targets_build_queue():
    targets("bin/codeteam-buildq", {"loops": False, "runners": False, "buildq": True})


def test_targets_hang_helper():
    targets("share/codeteam_hang.py", {"loops": False, "runners": False, "buildq": True})


def test_targets_launchd_module():
    targets("share/codeteam_launchd.py", {"loops": True, "runners": True, "buildq": False})


def test_targets_docs():
    targets("docs/readme.md", {"loops": False, "runners": False, "buildq": False})


def test_targets_combined():
    assert cl.restart_targets(["v2/bin/codeteam2", "bin/codeteam-land", "share/codeteam_hang.py"]) == {
        "loops": True, "runners": True, "buildq": True}


def test_own_checkout_resolves_symlink():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = team_at(root)
        alias = root / "alias"
        alias.symlink_to(team.repo, target_is_directory=True)
        team.repo = alias
        with patch.object(cl, "HERE", team.repo.resolve() / "bin"):
            assert cl.own_checkout(team) is True


def test_other_checkout_is_not_own():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        with patch.object(cl, "HERE", Path(tmp) / "codeteam" / "bin"):
            assert cl.own_checkout(team) is False


def test_after_promote_of_a_product_repo_does_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = team_at(root, tools=False)
        with patch.object(cl, "HERE", root / "other" / "bin"), patch.object(cl, "out") as out, \
                patch.object(cl.codeteam_runner_jobs, "runner_jobs", jobs_of(team)) as jobs, \
                patch.object(cl.subprocess, "run") as run, patch.object(cl.os, "kill") as kill:
            cl.after_promote(team, OLD, TIP)
        assert out.call_count == jobs.call_count == run.call_count == kill.call_count == team.notify.call_count == 0
        assert not (team.dir / "restart").exists()


def test_after_promote_writes_runner_markers_for_installed_services():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = team_at(root, "first")
        second = team_at(root, "second")
        disabled = team_at(root, "disabled", land=False)
        with patch.object(cl, "HERE", root / "repo" / "bin"), patch.object(Path, "home", return_value=root), \
                patch.object(cl, "out", return_value="bin/codeteam-land\n"), \
                patch.object(cl.codeteam_runner_jobs, "runner_jobs", jobs_of(team, second)) as jobs, \
                patch.object(cl.subprocess, "run") as run, patch.object(cl.os, "kill") as kill:
            cl.after_promote(team, OLD, TIP)
        jobs.assert_called_once_with(team.repo, root / "Library" / "LaunchAgents")
        for target in (team, second):
            for cmd in ("queue-run", "recheck-run", "validate-run"):
                data = json.loads((target.dir / "restart" / f"{cmd}.json").read_text())
                assert data["tip"] == TIP and isinstance(data["requested"], str) and data["requested"]
                assert isinstance(data["requested_ts"], (int, float))
        assert not (disabled.dir / "restart").exists()
        assert not run.called and not kill.called


def test_after_promote_of_a_fork_restarts_its_runners_and_leaves_lanes_and_the_build_queue():
    """A v5.5 checkout's promotes run production's codeteam-land, and a team's runners may run the
    fork's. The fork's promote asks for the runners of the fork's program, whose manifests live elsewhere, and leaves
    production's lanes and build queue to production's own promotes."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        fork = team_at(root, "fork")
        sprocket = team_at(root / "sprocket", "sprocket")
        module = SimpleNamespace(refresh_lanes=Mock(return_value=[]))
        with patch.object(cl, "HERE", root / "production" / "bin"), patch.object(Path, "home", return_value=root), \
                patch.object(cl, "out", return_value="bin/codeteam-land\nteams/fork.toml\nbin/codeteam-buildq\n"), \
                patch.object(cl.codeteam_runner_jobs, "runner_jobs", jobs_of(sprocket)) as jobs, \
                patch.dict(sys.modules, {"codeteam_refresh_lanes": module}), \
                patch.object(cl, "request_buildq_restart") as buildq, \
                patch.object(cl.subprocess, "run") as run, patch.object(cl.os, "kill") as kill:
            cl.after_promote(fork, OLD, TIP)
        jobs.assert_called_once_with(fork.repo, root / "Library" / "LaunchAgents")
        assert markers(sprocket) == ["queue-run.json", "recheck-run.json", "validate-run.json"]
        assert not (fork.dir / "restart").exists()
        assert not module.refresh_lanes.called and not buildq.called and not run.called and not kill.called
        fork.notify.assert_not_called()


def test_request_runner_restarts_marks_the_jobs_runner_jobs_names():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        installed = team_at(root, "installed")
        uninstalled = team_at(root, "uninstalled")
        with patch.object(cl.codeteam_runner_jobs, "runner_jobs", jobs_of(installed, commands=("queue-run",))):
            cl.request_runner_restarts(installed, TIP)
        request = json.loads((installed.dir / "restart" / "queue-run.json").read_text())
        assert request["tip"] == "0123456789abcdef0123"
        assert markers(installed) == ["queue-run.json"]
        assert not (uninstalled.dir / "restart").exists()
        assert cl.runner_restart(uninstalled, "queue-run") is False
        uninstalled.notify.assert_not_called()


def test_request_runner_restarts_notes_a_runner_whose_manifest_is_gone_and_marks_the_rest():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = team_at(root)
        gone = team_at(root / "gone", "gone")
        gone.manifest.unlink()
        with patch.object(cl.codeteam_runner_jobs, "runner_jobs", jobs_of(gone, team, commands=("queue-run",))), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            cl.request_runner_restarts(team, TIP)
        assert markers(team) == ["queue-run.json"]
        team.notify.assert_called_once()
        recipient, kind, text = team.notify.call_args.args
        assert (recipient, kind) == ("Skippy", "NOTE")
        assert text.startswith(f"{gone.manifest} not restarted at 0123456789: its manifest cannot be read: "
                               "FileNotFoundError")
        assert err.getvalue() == text + "\n"


def test_after_promote_restarts_only_running_loop_and_posts():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = team_at(root, "running")
        idle = team_at(root, "idle")
        program = team.repo / "v2" / "bin" / "codeteam2"
        events = []
        def run(args, **kwargs):
            events.append(("run", list(map(str, args))))
            if "ps" in str(args[0]):
                return SimpleNamespace(stdout=f"123 python3 {program} run {team.manifest}\n"
                                              f"124 python3 /other/v2/bin/codeteam2 run {idle.manifest}\n",
                                       stderr="", returncode=0)
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        with patch.object(cl, "HERE", team.repo / "bin"), patch.object(cl, "out", return_value="v2/codeteam2/x.py\n"), \
                patch.object(cl.subprocess, "run", side_effect=run), \
                patch.object(cl.os, "kill", side_effect=lambda pid, sig: events.append(("kill", pid, sig))), \
                patch.object(cl.Team, "notify") as notify:
            cl.after_promote(team, OLD, TIP)
        kills = [e for e in events if e[0] == "kill"]
        starts = [e for e in events if e[0] == "run" and "ensure-loop" in e[1]]
        assert kills == [("kill", 123, signal.SIGTERM)]
        assert len(starts) == 1 and starts[0][1] == [str(program), "ensure-loop", str(team.manifest)]
        assert events.index(kills[0]) < events.index(starts[0])
        assert notify.call_count == 1
        assert "running" in str(notify.call_args) and "0123456789" in str(notify.call_args)


def test_after_promote_ps_failure_notes_and_still_writes_runner_markers():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = team_at(root)
        calls = []
        def run(args, **kwargs):
            calls.append(list(map(str, args)))
            raise subprocess.CalledProcessError(1, args)
        with patch.object(cl, "HERE", team.repo / "bin"), \
                patch.object(cl, "out", return_value="v2/codeteam2/x.py\nbin/codeteam-land\n"), \
                patch.object(cl.codeteam_runner_jobs, "runner_jobs", jobs_of(team)), \
                patch.object(cl.subprocess, "run", side_effect=run), patch.object(cl.os, "kill") as kill, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            cl.after_promote(team, OLD, TIP)
        assert calls == [["ps", "-axo", "pid=,command="]]
        assert not kill.called
        for cmd in ("queue-run", "recheck-run", "validate-run"):
            assert json.loads((team.dir / "restart" / f"{cmd}.json").read_text())["tip"] == TIP
        team.notify.assert_called_once()
        recipient, kind, text = team.notify.call_args.args
        assert (recipient, kind) == ("Skippy", "NOTE")
        assert text.startswith("codeteam2 loops not restarted at 0123456789: listing the processes with ps failed:")
        assert err.getvalue() == text + "\n"


def test_restart_loops_ensure_loop_failure_logs_note_and_continues():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        failed = team_at(root, "failed")
        healthy = team_at(root, "healthy")
        with patch.object(cl.os, "kill") as kill, \
                patch.object(cl.subprocess, "run", side_effect=[
                    subprocess.CalledProcessError(2, ["fake", "ensure-loop"]), SimpleNamespace(returncode=0)]) as run, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            cl.restart_loops([failed, healthy], TIP, {failed.manifest: [123], healthy.manifest: [456]},
                             Path("/p/v2/bin/codeteam2"))
        assert [call.args for call in kill.call_args_list] == [(123, signal.SIGTERM), (456, signal.SIGTERM)]
        assert [call.args[0] for call in run.call_args_list] == [
            ["/p/v2/bin/codeteam2", "ensure-loop", str(failed.manifest)],
            ["/p/v2/bin/codeteam2", "ensure-loop", str(healthy.manifest)]]
        failed.notify.assert_called_once()
        recipient, kind, text = failed.notify.call_args.args
        assert (recipient, kind) == ("Skippy", "NOTE")
        assert "Could not restart codeteam2 loop for failed at 0123456789: ensure-loop failed:" in text
        assert "exit status 2" in text
        assert err.getvalue() == text + "\n"
        healthy.notify.assert_called_once_with("Skippy", "NOTE",
            "Restarted codeteam2 loop for healthy at 0123456789; no session ended.")


def test_restart_loops_lock_timeout_logs_note_and_continues():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        stuck = team_at(root, "stuck")
        healthy = team_at(root, "healthy")
        lock = stuck.root / "team" / "v2" / "run.lock"
        lock.parent.mkdir(parents=True)
        lock.touch()
        with patch.object(cl.os, "kill"), patch.object(cl.fcntl, "flock", side_effect=BlockingIOError) as flock, \
                patch.object(cl.time, "monotonic", side_effect=[0, 1, 30]), patch.object(cl.time, "sleep") as sleep, \
                patch.object(cl.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            cl.restart_loops([stuck, healthy], TIP, {stuck.manifest: [123], healthy.manifest: [456]},
                             Path("/p/v2/bin/codeteam2"))
        assert [call.args[1] for call in flock.call_args_list] == [
            cl.fcntl.LOCK_EX | cl.fcntl.LOCK_NB, cl.fcntl.LOCK_EX | cl.fcntl.LOCK_NB]
        sleep.assert_called_once_with(0.1)
        run.assert_called_once()
        assert run.call_args.args[0][-1] == str(healthy.manifest)
        stuck.notify.assert_called_once_with("Skippy", "NOTE",
            "Could not restart codeteam2 loop for stuck at 0123456789: run.lock still held after 30 s.")
        assert err.getvalue() == "Could not restart codeteam2 loop for stuck at 0123456789: run.lock still held after 30 s.\n"
        healthy.notify.assert_called_once_with("Skippy", "NOTE",
            "Restarted codeteam2 loop for healthy at 0123456789; no session ended.")


def test_restart_loops_waits_for_lock_release_before_ensure_loop():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        lock = team.root / "team" / "v2" / "run.lock"
        lock.parent.mkdir(parents=True)
        lock.touch()
        events = []
        def flock(file, operation):
            events.append(operation)
            if len(events) == 1:
                raise BlockingIOError
        with patch.object(cl.os, "kill"), patch.object(cl.fcntl, "flock", side_effect=flock), \
                patch.object(cl.time, "monotonic", side_effect=[0, 1]), patch.object(cl.time, "sleep"), \
                patch.object(cl.subprocess, "run", side_effect=lambda *args, **kwargs: events.append("ensure-loop")):
            cl.restart_loops([team], TIP, {team.manifest: [123]}, Path("/p/v2/bin/codeteam2"))
        assert events == [cl.fcntl.LOCK_EX | cl.fcntl.LOCK_NB, cl.fcntl.LOCK_EX | cl.fcntl.LOCK_NB,
                          cl.fcntl.LOCK_UN, "ensure-loop"]
        team.notify.assert_called_once_with("Skippy", "NOTE",
            "Restarted codeteam2 loop for sample at 0123456789; no session ended.")


X = Path("/x/v2/bin/codeteam2")


def test_loop_processes_homebrew_framework_python():
    listing = ("  372 /opt/homebrew/Cellar/python@3.15/3.15.0_1/Frameworks/Python.framework/Versions/3.15/"
               "Resources/Python.app/Contents/MacOS/Python /srv/codeteam/v2/bin/codeteam2 run "
               "/srv/codeteam/teams/codeteam.toml\n")
    with patch.object(cl.subprocess, "run", return_value=SimpleNamespace(stdout=listing)):
        assert cl.loop_processes(Path("/srv/codeteam/v2/bin/codeteam2")) == {
            Path("/srv/codeteam/teams/codeteam.toml").resolve(): [372]}


def test_loop_processes_usr_bin_python3():
    with patch.object(cl.subprocess, "run", return_value=SimpleNamespace(
            stdout="  373 /usr/bin/python3 /x/v2/bin/codeteam2 run /m/a.toml\n")):
        assert cl.loop_processes(X) == {Path("/m/a.toml").resolve(): [373]}


def test_loop_processes_python315():
    with patch.object(cl.subprocess, "run", return_value=SimpleNamespace(
            stdout="  374 python3.15 /x/v2/bin/codeteam2 run /m/a.toml\n")):
        assert cl.loop_processes(X) == {Path("/m/a.toml").resolve(): [374]}


def test_loop_processes_python_flags():
    with patch.object(cl.subprocess, "run", return_value=SimpleNamespace(
            stdout="  375 python3 -u /x/v2/bin/codeteam2 run /m/a.toml\n")):
        assert cl.loop_processes(X) == {Path("/m/a.toml").resolve(): [375]}


def test_loop_processes_direct_script():
    with patch.object(cl.subprocess, "run", return_value=SimpleNamespace(
            stdout="  376 /x/v2/bin/codeteam2 run /m/a.toml\n")):
        assert cl.loop_processes(X) == {Path("/m/a.toml").resolve(): [376]}


def test_loop_processes_relative_manifest():
    with tempfile.TemporaryDirectory() as tmp:
        previous = Path.cwd()
        try:
            os.chdir(tmp)
            with patch.object(cl.subprocess, "run", return_value=SimpleNamespace(
                    stdout="  377 python3 /x/v2/bin/codeteam2 run teams/a.toml\n")):
                assert cl.loop_processes(X) == {(Path(tmp) / "teams/a.toml").resolve(): [377]}
        finally:
            os.chdir(previous)


def test_loop_processes_ignores_session():
    with patch.object(cl.subprocess, "run", return_value=SimpleNamespace(
            stdout="  900 claude --session example codeteam2 run /m/a.toml\n")):
        assert cl.loop_processes(X) == {}


def test_loop_processes_ignores_shell_wrapper():
    with patch.object(cl.subprocess, "run", return_value=SimpleNamespace(
            stdout="  901 /bin/zsh -c /x/v2/bin/codeteam2 run /m/a.toml\n")):
        assert cl.loop_processes(X) == {}


def test_loop_processes_ignores_quoted_shell_wrapper():
    with patch.object(cl.subprocess, "run", return_value=SimpleNamespace(
            stdout="  903 zsh -c 'cd /x && python3 codeteam2 run /m/a.toml'\n")):
        assert cl.loop_processes(X) == {}


def test_loop_processes_ignores_grep():
    with patch.object(cl.subprocess, "run", return_value=SimpleNamespace(stdout="  902 grep codeteam2 run\n")):
        assert cl.loop_processes(X) == {}


def test_loop_processes_groups_mixed_listing():
    listing = ("  372 /opt/homebrew/Cellar/python@3.15/3.15.0_1/Frameworks/Python.framework/Versions/3.15/"
               "Resources/Python.app/Contents/MacOS/Python /srv/codeteam/v2/bin/codeteam2 run "
               "/srv/codeteam/teams/codeteam.toml\n"
               "  378 python3 /x/v2/bin/codeteam2 run /srv/codeteam/teams/codeteam.toml\n"
               "  900 claude --session example codeteam2 run /m/a.toml\n"
               "  901 /bin/zsh -c /x/v2/bin/codeteam2 run /m/a.toml\n"
               "  903 zsh -c 'cd /x && python3 codeteam2 run /m/a.toml'\n"
               "  902 grep codeteam2 run\n")
    with patch.object(cl.subprocess, "run", return_value=SimpleNamespace(stdout=listing)):
        assert cl.loop_processes(Path("/srv/codeteam/v2/bin/codeteam2")) == {
            Path("/srv/codeteam/teams/codeteam.toml").resolve(): [372]}
        assert cl.loop_processes(X) == {Path("/srv/codeteam/teams/codeteam.toml").resolve(): [378]}


def assert_after_promote_no_loop_note(listing):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = team_at(root)
        with patch.object(cl, "HERE", team.repo / "bin"), \
                patch.object(cl, "out", return_value="v2/codeteam2/x.py\n"), \
                patch.object(cl.subprocess, "run", return_value=SimpleNamespace(stdout=listing, stderr="", returncode=0)) as run, \
                patch.object(cl.os, "kill") as kill, patch.object(cl.Team, "notify") as others, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            cl.after_promote(team, OLD, TIP)
        # The NOTE goes through the promoting team; no other team's Team object sends anything.
        others.assert_not_called()
        assert team.notify.call_count == 1
        recipient, kind, text = team.notify.call_args.args
        assert err.getvalue() == text + "\n"
        assert (recipient, kind) == ("Skippy", "NOTE")
        assert text == (f"codeteam2 loops not restarted at 0123456789: ps listed no codeteam2 run loop of "
                        f"{team.repo / 'v2' / 'bin' / 'codeteam2'}; check the loops and restart them by hand")
        kill.assert_not_called()
        assert not any("ensure-loop" in call.args[0] for call in run.call_args_list)


def test_after_promote_notes_when_no_loop_found():
    assert_after_promote_no_loop_note("  101 /usr/bin/other-process\n")


def test_after_promote_notes_when_only_another_checkout_s_loop_found():
    assert_after_promote_no_loop_note("  102 python3 /x/v2/bin/codeteam2 run /elsewhere/x.toml\n")


def test_after_promote_running_and_down_team_only_notifies_restart():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = team_at(root, "running")
        idle = team_at(root, "idle")
        listing = f"  123 python3 {team.repo}/v2/bin/codeteam2 run {team.manifest}\n"
        with patch.object(cl, "HERE", team.repo / "bin"), \
                patch.object(cl, "out", return_value="v2/codeteam2/x.py\n"), \
                patch.object(cl.subprocess, "run", return_value=SimpleNamespace(stdout=listing, stderr="", returncode=0)) as run, \
                patch.object(cl.os, "kill") as kill, patch.object(cl.Team, "notify") as notify:
            cl.after_promote(team, OLD, TIP)
        notify.assert_called_once_with("Skippy", "NOTE",
            "Restarted codeteam2 loop for running at 0123456789; no session ended.")
        kill.assert_called_once_with(123, signal.SIGTERM)
        starts = [call.args[0] for call in run.call_args_list if "ensure-loop" in call.args[0]]
        assert len(starts) == 1 and str(team.manifest) in starts[0] and str(idle.manifest) not in starts[0]


def test_after_promote_of_a_fork_restarts_the_loops_of_its_program_with_its_program():
    """sprocket's loop runs a v5.5 checkout's codeteam2 on a manifest in the fork's teams/, and a v5.5 checkout's own loop runs
    production's: the fork's promote restarts sprocket's with the fork's program and leaves a v5.5 checkout's alone."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        fork = team_at(root, "fork")
        sprocket = team_at(root / "sprocket", "sprocket")
        program = fork.repo / "v2" / "bin" / "codeteam2"
        listing = (f"  123 python3 {program} run {sprocket.manifest}\n"
                   f"  124 python3 {root}/production/v2/bin/codeteam2 run {fork.manifest}\n")
        with patch.object(cl, "HERE", root / "production" / "bin"), \
                patch.object(cl, "out", return_value="v2/codeteam2/x.py\n"), \
                patch.object(cl.subprocess, "run", return_value=SimpleNamespace(stdout=listing, stderr="", returncode=0)) as run, \
                patch.object(cl.os, "kill") as kill, patch.object(cl.Team, "notify") as notify:
            cl.after_promote(fork, OLD, TIP)
        kill.assert_called_once_with(123, signal.SIGTERM)
        starts = [call.args[0] for call in run.call_args_list if "ensure-loop" in call.args[0]]
        assert starts == [[str(program), "ensure-loop", str(sprocket.manifest)]]
        notify.assert_called_once_with("Skippy", "NOTE",
            "Restarted codeteam2 loop for sprocket at 0123456789; no session ended.")
        fork.notify.assert_not_called()


RUNNERS = {"queue-run": ("cmd_queue_run", "land"), "recheck-run": ("cmd_recheck_run", "recheck"),
           "validate-run": ("cmd_validate_run", "validate")}


def runner_marker_case(command, halted):
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        path = marker(team, command)
        with patch.object(cl, "halted", return_value=halted) as halt, \
                patch.object(cl, "advance_queue") as queue, patch.object(cl, "recheck_one") as recheck, \
                patch.object(cl, "validate_one") as validate, patch.object(cl, "queue_maintenance", return_value=(0, 0)), \
                patch.object(cl, "read_recheck", return_value=[]), patch.object(cl, "stage6_target", return_value=None), \
                patch.object(cl, "alpha_cfg", return_value=None):
            with contextlib.redirect_stdout(io.StringIO()) as log:
                getattr(cl, RUNNERS[command][0])(team, SimpleNamespace(once=True))
        assert not path.exists(), f"{command} did not consume marker"
        assert not queue.called and not recheck.called and not validate.called
        assert not halt.called, "restart check must precede halted check"
        # The runner's own log says it, not a NOTE to the orchestrator.
        team.notify.assert_not_called()
        text = log.getvalue()
        assert f"restarting com.codeteam.codeteam-{RUNNERS[command][1]}.sample" in text, text
        assert "codeteam 0123456789" in text and "it had no job running" in text, text


def runner_no_marker_case(command):
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        with patch.object(cl, "halted", return_value=False), \
                patch.object(cl, "queue_maintenance", return_value=(0, 0)), patch.object(cl, "advance_queue") as queue, \
                patch.object(cl, "read_recheck", return_value=[{"wo": "feature", "M": TIP}]), \
                patch.object(cl, "pending_recheck", return_value=0), patch.object(cl, "recheck_one") as recheck, \
                patch.object(cl, "stage6_target", return_value=TIP), patch.object(cl, "alpha_cfg", return_value={"local": True}), \
                patch.object(cl, "validate_due", return_value=True), \
                patch.object(cl, "validate_one", return_value={"commit": TIP, "result": "fail", "tests": []}) as validate:
            getattr(cl, RUNNERS[command][0])(team, SimpleNamespace(once=True))
        assert {"queue-run": queue, "recheck-run": recheck, "validate-run": validate}[command].call_count == 1
        assert not team.notify.called


# The queue-run cases only: advance_queue and queue_maintenance are faked, so they take no real lock. The
# recheck-run and validate-run cases take their runner's real flock, and every waited case the real Lock (queue-run,
# through advance_queue) or the runner's flock: tests/integration/land-v52-restart.py installs those.
for command in ("queue-run",):
    name = command.replace("-", "_")
    for halted in (False, True):
        def marker_test(command=command, halted=halted):
            runner_marker_case(command, halted)
        marker_test.__name__ = f"test_{name}_marker_while_{'halted' if halted else 'active'}"
        globals()[marker_test.__name__] = marker_test
    def no_marker_test(command=command):
        runner_no_marker_case(command)
    no_marker_test.__name__ = f"test_{name}_without_marker_continues"
    globals()[no_marker_test.__name__] = no_marker_test


def test_targets_kinds_switch_helper():
    assert cl.restart_targets(["share/codeteam_kinds_switch.py"])["runners"] is True


def test_targets_unit_record_refusal_helper():
    assert cl.restart_targets(["share/codeteam_unit_record_refusal.py"])["runners"] is True


def test_targets_refresh_lanes_helper():
    assert cl.restart_targets(["share/codeteam_refresh_lanes.py"])["runners"] is True


def test_targets_runner_jobs_helper():
    assert cl.restart_targets(["share/codeteam_runner_jobs.py"])["runners"] is True


def test_targets_every_module_the_programs_import():
    """The lists follow the programs' own imports, so a module added to codeteam-land (finding_holds) or
    to the build queue's runner (the team slot) restarts what loads it without a hand-kept name."""
    assert cl.restart_targets(["share/codeteam_finding_holds.py"])["runners"] is True
    assert cl.restart_targets(["share/codeteam_tm.py"])["runners"] is True
    assert cl.restart_targets(["share/codeteam_team_slot.py"]) == {"loops": False, "runners": False, "buildq": True}
    assert cl.restart_targets(["share/codeteam_job_team.py"])["buildq"] is True       # through team_slot's import


def test_after_promote_refreshes_changed_manifests():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = team_at(root, "sample")
        team_at(root, "another")
        (team.repo / "teams").symlink_to(root / "teams", target_is_directory=True)
        refresh = Mock(return_value=[])
        module = SimpleNamespace(refresh_lanes=refresh)
        with patch.dict(sys.modules, {"codeteam_refresh_lanes": module}), \
                patch.object(cl, "HERE", team.repo / "bin"), \
                patch.object(cl, "out", return_value="teams/sample.toml\n"):
            cl.after_promote(team, OLD, TIP)
        refresh.assert_called_once_with(team.repo, ["teams/sample.toml"],
            [team.repo / "teams" / "another.toml", team.repo / "teams" / "sample.toml"],
            team.repo / "bin" / "codeteam")
        team.notify.assert_not_called()


def test_after_promote_reports_each_refresh_failure():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = team_at(root, "sample")
        (team.repo / "teams").symlink_to(root / "teams", target_is_directory=True)
        messages = ["failed sample.toml", "failed another.toml"]
        module = SimpleNamespace(refresh_lanes=Mock(return_value=messages))
        with patch.dict(sys.modules, {"codeteam_refresh_lanes": module}), \
                patch.object(cl, "HERE", team.repo / "bin"), \
                patch.object(cl, "out", return_value="teams/sample.toml\n"), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            cl.after_promote(team, OLD, TIP)
        assert err.getvalue() == "failed sample.toml\nfailed another.toml\n"
        assert team.notify.call_args_list == [
            call("Skippy", "NOTE", "failed sample.toml"),
            call("Skippy", "NOTE", "failed another.toml")]


def test_after_promote_notes_refresh_exception_and_restarts_runners():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = team_at(root, "sample")
        (team.repo / "teams").symlink_to(root / "teams", target_is_directory=True)
        module = SimpleNamespace(refresh_lanes=Mock(side_effect=RuntimeError("boom")))
        with patch.dict(sys.modules, {"codeteam_refresh_lanes": module}), \
                patch.object(cl, "HERE", team.repo / "bin"), \
                patch.object(cl, "out", return_value="bin/codeteam-land\n"), \
                patch.object(cl.codeteam_runner_jobs, "runner_jobs", jobs_of(team, commands=("queue-run",))), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            cl.after_promote(team, OLD, TIP)
        message = f"team.json lanes not refreshed at {TIP[:10]}: RuntimeError: boom"
        team.notify.assert_called_once_with("Skippy", "NOTE", message)
        assert err.getvalue() == message + "\n"
        request = json.loads((team.dir / "restart" / "queue-run.json").read_text())
        assert request["tip"] == TIP


failed = 0
for test in [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]:
    if len(sys.argv) > 1 and test.__name__ not in sys.argv[1:]:
        continue
    try:
        test()
        print(f"  PASS {test.__name__}")
    except (Exception, SystemExit) as exc:
        failed += 1
        print(f"  FAIL {test.__name__}: {type(exc).__name__}: {exc}")
print(f"{failed} failed" if failed else "all passed")
sys.exit(1 if failed else 0)
