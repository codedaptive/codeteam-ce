#!/usr/bin/env -S python3 -u
"""Stage 7 restart contracts with scratch manifests and fake processes: integration tests through
stage7's real landing Lock, after_promote's build-queue request under the real restart lock, and the real locks the
generated runner cases take (the recheck and validation runners' flocks, advance_queue's Lock). The unit tests are in
tests/unit/land-v52-restart.py. It also holds the build-queue restart's at-once
step and the stage runs and runner ticks that go on while a restart request is pending, moved from
tests/unit/land-v52-tidy.py."""
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
    # A checkout of codeteam's tools: after_promote does nothing for a product's repo.
    (repo / "bin").mkdir(parents=True, exist_ok=True)
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


def test_after_promote_buildq_requests_restart():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = team_at(root)
        # What the build queue runs is read from its program's imports in the promoted tree.
        (team.repo / "bin" / "codeteam-buildq").write_text("import codeteam_hang\n")
        (team.repo / "share").mkdir()
        (team.repo / "share" / "codeteam_hang.py").touch()
        with patch.dict(os.environ, {"CODETEAM_QUEUE_DIR": str(root / "queue")}), \
                patch.object(cl, "HERE", team.repo / "bin"), \
                patch.object(cl, "out", return_value="share/codeteam_hang.py\n"), \
                patch.object(cl.subprocess, "run") as run, patch.object(cl.os, "kill") as kill, \
                patch.object(cl, "spawn") as spawn:
            cl.after_promote(team, OLD, TIP)
        path = root / "restart" / "buildq.json"
        assert path.exists(), "build queue restart marker not written"
        data = json.loads(path.read_text())
        assert data["tip"] == TIP and data["files"] == ["share/codeteam_hang.py"] and "waited" not in data
        assert not any("restart it by hand" in str(c) for c in team.notify.call_args_list)
        assert not run.called and not kill.called and not spawn.called


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
            if command == "recheck-run":
                return {"tests": []}            # recheck_one's result; run_recheck_tick reads its checkout
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
            with contextlib.redirect_stdout(io.StringIO()) as log:
                try:
                    getattr(cl, RUNNERS[command][0])(team, SimpleNamespace(once=False))
                except StopLoop:
                    pass
        restarts = [line for line in log.getvalue().splitlines() if "restarting com.codeteam.codeteam-" in line]
        assert len(restarts) == 1, f"{command} did not log its restart after the job: {log.getvalue()}"
        assert expected in restarts[0], restarts
        team.notify.assert_not_called()
        assert not (team.dir / "restart" / f"{command}.json").exists()


# The recheck-run and validate-run marker cases, which take their runner's real flock, and every runner's waited
# cases, which take the real Lock (queue-run, through advance_queue) or the runner's flock. The queue-run marker
# cases fake advance_queue and queue_maintenance and take no real lock: tests/unit/land-v52-restart.py installs them.
for command in RUNNERS:
    name = command.replace("-", "_")
    if command != "queue-run":
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


def make_team(root):
    repo = root / "repo"
    repo.mkdir()
    manifest = root / "sample.toml"
    manifest.write_text(f'repo = "{repo}"\nworktree_root = "{root / "team"}"\n'
                        '[[lanes]]\nname = "A"\npath = "A"\n'
                        '[[assistants]]\nname = "Nagatha"\n[land]\norchestrator = "Skippy"\n')
    team = cl.Team(str(manifest))
    team.notify = Mock()
    return team


def holder_row(stages, pid, team_key, wos, name="hold"):
    stages.mkdir(parents=True, exist_ok=True)
    (stages / f"{name}.json").write_text(json.dumps({"stage": "Stage 2", "name": f"check of {', '.join(wos)}",
                                                     "pid": pid, "started": "06:10", "team": team_key, "wos": wos}))


def queue_marker(qdir):
    p = qdir.parent / "restart" / "buildq.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"requested": "now", "requested_ts": 1, "tip": "0123456789abcdef", "files": []}))
    return p


def job(qdir, ticket, state, landing, key="unit A"):
    qdir.mkdir(parents=True, exist_ok=True)
    (qdir / f"{ticket}.json").write_text(json.dumps({"ticket": ticket, "key": key, "state": state,
                                                       "env": {"CODETEAM_LANDING": landing}}))


def test_restart_request_records_tip_files_without_waited():
    with tempfile.TemporaryDirectory() as tmp:
        qdir = Path(tmp) / "queue"
        cl.request_buildq_restart(qdir, "0123456789abcdef", ["share/codeteam_hang.py"])
        row = json.loads((qdir.parent / "restart" / "buildq.json").read_text())
        assert row["tip"] == "0123456789abcdef" and row["files"] == ["share/codeteam_hang.py"]
        assert row["requested"] and isinstance(row["requested_ts"], (int, float))
        assert set(row) == {"requested", "requested_ts", "tip", "files"}


def test_restart_at_once_with_live_stage_and_queued_job():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = make_team(root)
        qdir = root / "queue"
        p = queue_marker(qdir)
        # A request written by an older landing tool carries "waited"; one pending across the deploy is still done at once.
        p.write_text(json.dumps({**json.loads(p.read_text()), "waited": []}))
        holder_row(p.parent / "stages", os.getpid(), "/t.toml", ["a"], "live")
        job(qdir, "t1", "queued", "1")
        kick = Mock()
        assert cl.buildq_restart_step(team, qdir=qdir, kickstart=kick) is True
        kick.assert_called_once_with()
        assert not p.exists()
        team.notify.assert_called_once_with("Skippy", "NOTE", "Restarted com.codeteam.codeteam-buildq for main 0123456789")


def test_restart_failure_posts_and_releases_marker():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = make_team(root)
        qdir = root / "queue"
        cl.request_buildq_restart(qdir, "0123456789abcdef", [])
        p = qdir.parent / "restart" / "buildq.json"
        kick = Mock(side_effect=OSError("fake failure"))
        assert cl.buildq_restart_step(team, qdir=qdir, kickstart=kick) is True
        assert not p.exists()
        assert "Could not restart com.codeteam.codeteam-buildq at 0123456789: fake failure; restart it by hand" in team.notify.call_args.args[2]


def test_restart_without_marker_does_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = make_team(root)
        kick = Mock()
        assert cl.buildq_restart_step(team, qdir=root / "queue", kickstart=kick) is False
        kick.assert_not_called()
        team.notify.assert_not_called()


def test_stage2_runs_at_once_with_restart_pending():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = make_team(root)
        qdir = root / "queue"
        p = queue_marker(qdir)
        record = {"wo": "w", "zone": "A", "tree": str(root), "branch": "w"}
        sleep = Mock(side_effect=lambda *_: p.unlink(missing_ok=True))
        kick = Mock()
        with patch.dict(os.environ, {"CODETEAM_QUEUE_DIR": str(qdir)}), patch.object(cl, "own_checkout", return_value=False), \
                patch.object(cl, "buildq_restart_step", kick), patch.object(cl.time, "sleep", sleep), \
                patch.object(cl, "checked_members", return_value=[(record, False)]) as checked, \
                patch.object(cl, "out", return_value="hash"), patch.object(cl, "merge_checked_base"), \
                patch.object(cl, "changed_files", return_value=[]), patch.object(cl, "check_combined_members", return_value=(["A"], [])), \
                patch.object(cl, "queue_notices"), patch.object(cl, "stage3_record", return_value={"wo": "w", "reviewers": {}, "seen": {}, "state": "land"}), contextlib.redirect_stderr(io.StringIO()), \
                contextlib.redirect_stdout(io.StringIO()):
            cl.cmd_land(team, SimpleNamespace(wo="w", with_=[], untested=False))
        checked.assert_called_once()
        sleep.assert_not_called()
        kick.assert_not_called()
        assert p.exists()
        assert len(list((team.dir / "queue").glob("*.json"))) == 1


def test_stage5_rechecks_with_restart_pending():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = make_team(root)
        qdir = root / "queue"
        queue_marker(qdir)
        row = {"wo": "w", "M": "0123456789abcdef"}
        (team.dir / "recheck.jsonl").write_text(json.dumps(row) + "\n")
        with patch.dict(os.environ, {"CODETEAM_QUEUE_DIR": str(qdir)}), patch.object(cl, "halted", return_value=False), \
                patch.object(cl, "recheck_one", return_value={}) as one:
            cl.cmd_recheck_run(team, SimpleNamespace(once=True))
        one.assert_called_once()


def test_local_stage6_validates_with_restart_pending():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = make_team(root)
        qdir = root / "queue"
        queue_marker(qdir)
        with patch.dict(os.environ, {"CODETEAM_QUEUE_DIR": str(qdir)}), patch.object(cl, "own_checkout", return_value=False), \
                patch.object(cl, "halted", return_value=False), patch.object(cl, "stage6_target", return_value="0123456789abcdef"), \
                patch.object(cl, "alpha_cfg", return_value={"local": True}), patch.object(cl, "validate_due", return_value=True), \
                patch.object(cl, "validate_one", return_value={"commit": "0123456789abcdef", "result": "fail", "tests": []}) as one:
            cl.cmd_validate_run(team, SimpleNamespace(once=True))
        one.assert_called_once()


def test_remote_stage6_still_runs_with_restart_pending():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = make_team(root)
        qdir = root / "queue"
        queue_marker(qdir)
        result = {"commit": "0123456789abcdef", "result": "fail", "tests": []}
        with patch.dict(os.environ, {"CODETEAM_QUEUE_DIR": str(qdir)}), patch.object(cl, "own_checkout", return_value=False), \
                patch.object(cl, "halted", return_value=False), patch.object(cl, "stage6_target", return_value="0123456789abcdef"), \
                patch.object(cl, "alpha_cfg", return_value={"local": False}), patch.object(cl, "validate_due", return_value=True), \
                patch.object(cl, "validate_one", return_value=result) as one:
            cl.cmd_validate_run(team, SimpleNamespace(once=True))
        one.assert_called_once()


def test_halted_queue_runner_drives_restart_before_halted_check():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        events = []
        with patch.object(cl, "own_checkout", return_value=True), \
                patch.object(cl, "buildq_restart_step", side_effect=lambda *_: events.append("restart"), create=True), \
                patch.object(cl, "halted", side_effect=lambda *_: events.append("halted") or True):
            cl.cmd_queue_run(team, SimpleNamespace(once=True))
        assert events == ["restart", "halted"], events


def test_validate_runner_drives_restart_before_own_runner_restart():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        events = []
        with patch.object(cl, "own_checkout", return_value=True), \
                patch.object(cl, "buildq_restart_step", side_effect=lambda *_: events.append("buildq"), create=True), \
                patch.object(cl, "runner_restart", side_effect=lambda *_: events.append("runner") or True):
            cl.cmd_validate_run(team, SimpleNamespace(once=True))
        assert events == ["buildq", "runner"], events


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
