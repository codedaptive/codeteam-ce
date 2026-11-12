#!/usr/bin/env -S python3 -u
"""Stage 7 restart contracts with scratch manifests and fake processes."""
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
from unittest.mock import Mock, patch

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


def team_at(root, name="sample", land=True):
    teams = root / "teams"
    teams.mkdir(exist_ok=True)
    repo = root / "repo"
    repo.mkdir(exist_ok=True)
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


def targets(path, expected):
    assert cl.restart_targets([path]) == expected


def test_targets_codeteam2():
    targets("v2/codeteam2/x.py", {"loops": True, "runners": False, "buildq": False})


def test_targets_v2_bin():
    targets("v2/bin/codeteam2", {"loops": True, "runners": False, "buildq": False})


def test_targets_v1_cli():
    targets("bin/codeteam", {"loops": True, "runners": False, "buildq": False})


def test_targets_v2_tests():
    targets("v2/tests/x.py", {"loops": False, "runners": False, "buildq": False})


def test_targets_decisions():
    targets("v2/DECISIONS.md", {"loops": False, "runners": False, "buildq": False})


def test_targets_landing_program():
    targets("bin/codeteam-land", {"loops": False, "runners": True, "buildq": False})


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


def stage7_setup(team, already=False):
    def git(repo, *args, **kwargs):
        if args[:2] == ("merge-base", "--is-ancestor"):
            return SimpleNamespace(returncode=0 if args[-1] == "landing" or args[-2] == args[-1] or already else 1, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    def out(repo, *args):
        if args[:2] == ("rev-parse", "--abbrev-ref"): return "main"
        if args[0] == "diff": return ""
        return TIP if already else OLD
    return git, out


def test_stage7_calls_after_promote_with_old_and_new():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        (team.dir / "validation-results.jsonl").write_text(json.dumps({"commit": TIP, "result": "pass", "tests": []}) + "\n")
        git, out = stage7_setup(team)
        with patch.object(cl, "git", side_effect=git), patch.object(cl, "out", side_effect=out), \
                patch.object(cl, "stamp_docs", return_value=None), patch.object(cl, "own_checkout", return_value=True, create=True), \
                patch.object(cl, "after_promote", create=True) as after, contextlib.redirect_stdout(io.StringIO()):
            cl.stage7(team, TIP)
        assert after.call_args_list == [((team, OLD, TIP), {})]


def test_stage7_no_restart_when_base_did_not_move():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        (team.dir / "validation-results.jsonl").write_text(json.dumps({"commit": TIP, "result": "pass", "tests": []}) + "\n")
        git, out = stage7_setup(team, already=True)
        with patch.object(cl, "git", side_effect=git), patch.object(cl, "out", side_effect=out), \
                patch.object(cl, "after_promote", create=True) as after:
            cl.stage7(team, TIP)
        assert after.call_count == 0


def test_after_promote_other_checkout_does_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        with patch.object(cl, "HERE", Path(tmp) / "other" / "bin"), patch.object(cl, "out") as out, \
                patch.object(cl.subprocess, "run") as run, patch.object(cl.os, "kill") as kill:
            cl.after_promote(team, OLD, TIP)
        assert out.call_count == run.call_count == kill.call_count == team.notify.call_count == 0
        assert not (team.dir / "restart").exists()


def test_after_promote_writes_runner_markers_for_installed_services():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = team_at(root, "first")
        second = team_at(root, "second")
        disabled = team_at(root, "disabled", land=False)
        with patch.object(cl, "HERE", root / "repo" / "bin"), patch.object(Path, "home", return_value=root), \
                patch.object(cl, "out", return_value="bin/codeteam-land\n"), \
                patch.object(cl.subprocess, "run") as run, patch.object(cl.os, "kill") as kill:
            for target in (team, second):
                for _, _, plist, _ in cl.service_jobs(target):
                    plist.parent.mkdir(parents=True, exist_ok=True)
                    plist.touch()
            # Manifests are discovered under the checkout, not beside it.
            (root / "repo" / "teams").symlink_to(root / "teams", target_is_directory=True)
            cl.after_promote(team, OLD, TIP)
        for target in (team, second):
            for cmd in ("queue-run", "recheck-run", "validate-run"):
                data = json.loads((target.dir / "restart" / f"{cmd}.json").read_text())
                assert data["tip"] == TIP and isinstance(data["requested"], str) and data["requested"]
                assert isinstance(data["requested_ts"], (int, float))
        assert not (disabled.dir / "restart").exists()
        assert not run.called and not kill.called


def test_request_runner_restarts_marks_only_runners_with_plists():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        installed = team_at(root, "installed")
        uninstalled = team_at(root, "uninstalled")
        with patch.object(Path, "home", return_value=root):
            plist = root / "Library" / "LaunchAgents" / "com.codeteam.codeteam-land.installed.plist"
            plist.parent.mkdir(parents=True)
            plist.touch()
            cl.request_runner_restarts([installed, uninstalled], TIP)
        request = json.loads((installed.dir / "restart" / "queue-run.json").read_text())
        assert request["tip"] == "0123456789abcdef0123"
        assert not (installed.dir / "restart" / "recheck-run.json").exists()
        assert not (installed.dir / "restart" / "validate-run.json").exists()
        assert not (uninstalled.dir / "restart").exists()
        assert cl.runner_restart(uninstalled, "queue-run") is False
        uninstalled.notify.assert_not_called()


def test_after_promote_buildq_requests_restart():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = team_at(root)
        with patch.dict(os.environ, {"CODETEAM_QUEUE_DIR": str(root / "queue")}), \
                patch.object(cl, "HERE", team.repo / "bin"), \
                patch.object(cl, "out", return_value="share/codeteam_hang.py\n"), \
                patch.object(cl.subprocess, "run") as run, patch.object(cl.os, "kill") as kill, \
                patch.object(cl, "spawn") as spawn:
            cl.after_promote(team, OLD, TIP)
        path = root / "restart" / "buildq.json"
        assert path.exists(), "build queue restart marker not written"
        data = json.loads(path.read_text())
        assert data["tip"] == TIP and data["files"] == ["share/codeteam_hang.py"] and data["waited"] == []
        assert not any("restart it by hand" in str(c) for c in team.notify.call_args_list)
        assert not run.called and not kill.called and not spawn.called


def test_after_promote_restarts_only_running_loop_and_posts():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = team_at(root, "running")
        idle = team_at(root, "idle")
        (team.repo / "teams").symlink_to(root / "teams", target_is_directory=True)
        events = []
        def run(args, **kwargs):
            events.append(("run", list(map(str, args))))
            if "pgrep" in str(args[0]):
                return SimpleNamespace(stdout=f"123 python3 codeteam2 run {team.manifest}\n", stderr="", returncode=0)
            if "ps" in str(args[0]):
                return SimpleNamespace(stdout=f"123 python3 codeteam2 run {team.manifest}\n", stderr="", returncode=0)
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        with patch.object(cl, "HERE", team.repo / "bin"), patch.object(cl, "out", return_value="v2/codeteam2/x.py\n"), \
                patch.object(cl.subprocess, "run", side_effect=run), \
                patch.object(cl.os, "kill", side_effect=lambda pid, sig: events.append(("kill", pid, sig))), \
                patch.object(cl.Team, "notify") as notify:
            cl.after_promote(team, OLD, TIP)
        kills = [e for e in events if e[0] == "kill"]
        starts = [e for e in events if e[0] == "run" and "ensure-loop" in e[1]]
        assert kills == [("kill", 123, signal.SIGTERM)]
        assert len(starts) == 1 and str(team.manifest) in starts[0][1] and str(idle.manifest) not in starts[0][1]
        assert events.index(kills[0]) < events.index(starts[0])
        assert notify.call_count == 1
        assert "running" in str(notify.call_args) and "0123456789" in str(notify.call_args)


def test_after_promote_ps_failure_notes_and_still_writes_runner_markers():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = team_at(root)
        (team.repo / "teams").symlink_to(root / "teams", target_is_directory=True)
        calls = []
        def run(args, **kwargs):
            calls.append(list(map(str, args)))
            raise subprocess.CalledProcessError(1, args)
        with patch.object(cl, "HERE", team.repo / "bin"), patch.object(Path, "home", return_value=root), \
                patch.object(cl, "out", return_value="v2/codeteam2/x.py\nbin/codeteam-land\n"), \
                patch.object(cl.subprocess, "run", side_effect=run), patch.object(cl.os, "kill") as kill, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            for _, _, plist, _ in cl.service_jobs(team):
                plist.parent.mkdir(parents=True, exist_ok=True)
                plist.touch()
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
            cl.restart_loops([failed, healthy], TIP, {failed.manifest: [123], healthy.manifest: [456]})
        assert [call.args for call in kill.call_args_list] == [(123, signal.SIGTERM), (456, signal.SIGTERM)]
        assert [call.args[0][-1] for call in run.call_args_list] == [str(failed.manifest), str(healthy.manifest)]
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
            cl.restart_loops([stuck, healthy], TIP, {stuck.manifest: [123], healthy.manifest: [456]})
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
            cl.restart_loops([team], TIP, {team.manifest: [123]})
        assert events == [cl.fcntl.LOCK_EX | cl.fcntl.LOCK_NB, cl.fcntl.LOCK_EX | cl.fcntl.LOCK_NB,
                          cl.fcntl.LOCK_UN, "ensure-loop"]
        team.notify.assert_called_once_with("Skippy", "NOTE",
            "Restarted codeteam2 loop for sample at 0123456789; no session ended.")


def test_loop_processes_homebrew_framework_python():
    listing = ("  372 /opt/homebrew/Cellar/python@3.15/3.15.0_1/Frameworks/Python.framework/Versions/3.15/"
               "Resources/Python.app/Contents/MacOS/Python /srv/codeteam/v2/bin/codeteam2 run "
               "/srv/codeteam/teams/codeteam.toml\n")
    with patch.object(cl.subprocess, "run", return_value=SimpleNamespace(stdout=listing)):
        assert cl.loop_processes() == {Path("/srv/codeteam/teams/codeteam.toml").resolve(): [372]}


def test_loop_processes_usr_bin_python3():
    with patch.object(cl.subprocess, "run", return_value=SimpleNamespace(
            stdout="  373 /usr/bin/python3 /x/v2/bin/codeteam2 run /m/a.toml\n")):
        assert cl.loop_processes() == {Path("/m/a.toml").resolve(): [373]}


def test_loop_processes_python315():
    with patch.object(cl.subprocess, "run", return_value=SimpleNamespace(
            stdout="  374 python3.15 /x/v2/bin/codeteam2 run /m/a.toml\n")):
        assert cl.loop_processes() == {Path("/m/a.toml").resolve(): [374]}


def test_loop_processes_python_flags():
    with patch.object(cl.subprocess, "run", return_value=SimpleNamespace(
            stdout="  375 python3 -u /x/v2/bin/codeteam2 run /m/a.toml\n")):
        assert cl.loop_processes() == {Path("/m/a.toml").resolve(): [375]}


def test_loop_processes_direct_script():
    with patch.object(cl.subprocess, "run", return_value=SimpleNamespace(
            stdout="  376 /x/v2/bin/codeteam2 run /m/a.toml\n")):
        assert cl.loop_processes() == {Path("/m/a.toml").resolve(): [376]}


def test_loop_processes_relative_manifest():
    with tempfile.TemporaryDirectory() as tmp:
        previous = Path.cwd()
        try:
            os.chdir(tmp)
            with patch.object(cl.subprocess, "run", return_value=SimpleNamespace(
                    stdout="  377 python3 /x/v2/bin/codeteam2 run teams/a.toml\n")):
                assert cl.loop_processes() == {(Path(tmp) / "teams/a.toml").resolve(): [377]}
        finally:
            os.chdir(previous)


def test_loop_processes_ignores_session():
    with patch.object(cl.subprocess, "run", return_value=SimpleNamespace(
            stdout="  900 claude --session example codeteam2 run /m/a.toml\n")):
        assert cl.loop_processes() == {}


def test_loop_processes_ignores_shell_wrapper():
    with patch.object(cl.subprocess, "run", return_value=SimpleNamespace(
            stdout="  901 /bin/zsh -c /x/v2/bin/codeteam2 run /m/a.toml\n")):
        assert cl.loop_processes() == {}


def test_loop_processes_ignores_quoted_shell_wrapper():
    with patch.object(cl.subprocess, "run", return_value=SimpleNamespace(
            stdout="  903 zsh -c 'cd /x && python3 codeteam2 run /m/a.toml'\n")):
        assert cl.loop_processes() == {}


def test_loop_processes_ignores_grep():
    with patch.object(cl.subprocess, "run", return_value=SimpleNamespace(stdout="  902 grep codeteam2 run\n")):
        assert cl.loop_processes() == {}


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
        assert cl.loop_processes() == {Path("/srv/codeteam/teams/codeteam.toml").resolve(): [372, 378]}


def assert_after_promote_no_loop_note(listing):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = team_at(root)
        (team.repo / "teams").symlink_to(root / "teams", target_is_directory=True)
        with patch.object(cl, "HERE", team.repo / "bin"), \
                patch.object(cl, "out", return_value="v2/codeteam2/x.py\n"), \
                patch.object(cl.subprocess, "run", return_value=SimpleNamespace(stdout=listing, stderr="", returncode=0)) as run, \
                patch.object(cl.os, "kill") as kill, patch.object(cl.Team, "notify") as others, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            cl.after_promote(team, OLD, TIP)
        # The NOTE goes through the promoting team; the teams/ manifests' own Team objects send nothing.
        others.assert_not_called()
        assert team.notify.call_count == 1
        recipient, kind, text = team.notify.call_args.args
        assert err.getvalue() == text + "\n"
        assert (recipient, kind) == ("Skippy", "NOTE")
        assert text == ("codeteam2 loops not restarted at 0123456789: ps listed no codeteam2 run loop for any team; "
                        "check the loops and restart them by hand")
        kill.assert_not_called()
        assert not any("ensure-loop" in call.args[0] for call in run.call_args_list)


def test_after_promote_notes_when_no_loop_found():
    assert_after_promote_no_loop_note("  101 /usr/bin/other-process\n")


def test_after_promote_notes_when_only_unrelated_manifest_loop_found():
    assert_after_promote_no_loop_note("  102 python3 /x/v2/bin/codeteam2 run /elsewhere/x.toml\n")


def test_after_promote_running_and_down_team_only_notifies_restart():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = team_at(root, "running")
        idle = team_at(root, "idle")
        (team.repo / "teams").symlink_to(root / "teams", target_is_directory=True)
        listing = f"  123 python3 /x/v2/bin/codeteam2 run {team.manifest}\n"
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
            getattr(cl, RUNNERS[command][0])(team, SimpleNamespace(once=True))
        assert not path.exists(), f"{command} did not consume marker"
        assert not queue.called and not recheck.called and not validate.called
        assert not halt.called, "restart check must precede halted check"
        assert team.notify.call_count == 1
        text = team.notify.call_args.args[2]
        assert f"Restarted com.codeteam.codeteam-{RUNNERS[command][1]}.sample" in text
        assert "main" in text and "0123456789" in text and "it had no job running" in text


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


class StopLoop(Exception):
    pass


def runner_waited_case(command, requested_ts, expected):
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        entry = team.dir / "queue" / "feature.json"
        entry.write_text(json.dumps({"wo": "feature", "wos": ["feature"], "tip": TIP, "base": OLD, "zones": [], "review": "land"}))
        def job(*args):
            marker(team, command, requested_ts)
            if command == "validate-run":
                return {"commit": TIP, "result": "fail", "tests": []}
            return True
        # A second halted check is a bounded escape on the pre-change runner.
        with patch.object(cl, "halted", side_effect=[False, StopLoop()]), \
                patch.object(cl.time, "time", return_value=100), patch.object(cl.time, "sleep"), \
                patch.object(cl, "queue_maintenance", return_value=(0, 0)), patch.object(cl, "prune_queue"), \
                patch.object(cl, "land_entry", side_effect=job), \
                patch.object(cl, "read_recheck", return_value=[{"wo": "feature", "M": TIP}]), \
                patch.object(cl, "pending_recheck", return_value=0), patch.object(cl, "recheck_one", side_effect=job), \
                patch.object(cl, "stage6_target", return_value=TIP), patch.object(cl, "alpha_cfg", return_value={"local": True}), \
                patch.object(cl, "validate_due", return_value=True), patch.object(cl, "validate_one", side_effect=job):
            try:
                getattr(cl, RUNNERS[command][0])(team, SimpleNamespace(once=False))
            except StopLoop:
                pass
        assert team.notify.call_count == 1, f"{command} did not announce restart after the job"
        assert expected in team.notify.call_args.args[2]
        assert not (team.dir / "restart" / f"{command}.json").exists()


for command in RUNNERS:
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
    waited = {"queue-run": "Stage 4 landing of feature", "recheck-run": "Stage 5 recheck of feature at M 0123456789",
              "validate-run": "Stage 6 validation at 0123456789"}[command]
    for requested_ts, expected, suffix in ((101, waited, "waited"), (99, "it had no job running", "not_waited")):
        def waited_test(command=command, requested_ts=requested_ts, expected=expected):
            runner_waited_case(command, requested_ts, expected)
        waited_test.__name__ = f"test_{name}_{suffix}"
        globals()[waited_test.__name__] = waited_test


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
