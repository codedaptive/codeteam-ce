import importlib.machinery
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
PID = 999999


@pytest.fixture
def buildq(monkeypatch):
    name = "codeteam_buildq"
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / "bin" / "codeteam-buildq"))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    loader.exec_module(module)
    return module


@pytest.fixture
def queue(buildq, monkeypatch, tmp_path):
    q = tmp_path / "run" / "queue"
    q.mkdir(parents=True)
    job = {
        "ticket": "test-ticket",
        "kind": "run",
        "class": "dev",
        "state": "running",
        "key": "one zone/tests",
        "command": ["swift", "test"],
        "submitted": 0,
        "tool": "zone-tool",
        "env": {"CODETEAM_HANG_WINDOW": "10", "CODETEAM_HANG_CPU_PCT": "1"},
        "record": str(tmp_path / "record.json"),
        "pid": PID,
        "started": 0,
    }
    (q / "test-ticket.json").write_text(json.dumps(job))
    runner = buildq.Runner(q, q.parent / "queue.toml")
    runner.jobs = {j["ticket"]: j for j in runner.queue.all()}
    kills = []
    monkeypatch.setattr(buildq, "kill_tree", lambda pid, sig: kills.append((pid, sig)))
    monkeypatch.setattr(buildq, "alive", lambda pid: True)
    monkeypatch.setenv("CODETEAM_HANG_WINDOW", "1000")
    monkeypatch.setenv("CODETEAM_HANG_CPU_PCT", "50")
    return runner, kills


def test_silent_idle_run_stops_after_backstop_window(queue):
    runner, kills = queue
    job = runner.jobs["test-ticket"]
    for now in range(0, 20, 5):
        runner.enforce_hang(job, now, {PID: 0.0})
        assert kills == []
        assert "stopped" not in runner.queue.read("test-ticket")

    runner.enforce_hang(job, 20, {PID: 0.0})
    assert kills == [(999999, 15)]
    saved = runner.queue.read("test-ticket")
    assert saved["stopped"] == 20
    assert saved["reason"].startswith("hung:")


def test_stopped_run_is_broken_even_with_fresh_pass_record(queue, buildq, monkeypatch):
    runner, _ = queue
    record = Path(runner.jobs["test-ticket"]["record"])
    record.write_text(json.dumps({"result": "PASS", "exit": 0}))
    runner.write("test-ticket", {"stopped": 20, "reason": "hung: silent idle run",
                                 "record_mtime": record.stat().st_mtime - 1})
    monkeypatch.setattr(buildq, "alive", lambda pid: False)

    runner.reconcile_run(runner.jobs["test-ticket"], {})

    saved = runner.queue.read("test-ticket")
    assert saved["state"] == "broken"
    assert saved["reason"].startswith("hung:")
    assert saved["reason"] == "hung: silent idle run"


def test_busy_run_is_never_killed(queue):
    runner, kills = queue
    job = runner.jobs["test-ticket"]
    for now in range(0, 2001, 5):
        runner.enforce_hang(job, now, {PID: now / 5.0})
    assert kills == []
    assert "stopped" not in runner.queue.read("test-ticket")


def test_growing_log_keeps_idle_run_alive(queue):
    runner, kills = queue
    job = runner.jobs["test-ticket"]
    log = runner.q / "test-ticket.log"
    for now in range(0, 401, 5):
        with log.open("ab") as output:
            output.write(b"progress\n")
        runner.enforce_hang(job, now, {PID: 0.0})
    assert kills == []
    assert "stopped" not in runner.queue.read("test-ticket")


def test_recent_unknown_samples_keep_idle_run_alive(queue):
    runner, kills = queue
    job = runner.jobs["test-ticket"]
    for now in range(0, 401, 5):
        cpu = None if now % 15 == 0 else {PID: 0.0}
        runner.enforce_hang(job, now, cpu)
    assert kills == []
    assert "stopped" not in runner.queue.read("test-ticket")


def test_runner_restart_starts_a_fresh_backstop_window(queue, buildq):
    runner, kills = queue
    job = runner.jobs["test-ticket"]
    runner.enforce_hang(job, 0, {PID: 0.0})
    runner.enforce_hang(job, 15, {PID: 0.0})
    restarted = buildq.Runner(runner.q, runner.conf)
    restarted.jobs = {j["ticket"]: j for j in restarted.queue.all()}
    job = restarted.jobs["test-ticket"]
    restarted.enforce_hang(job, 20, {PID: 0.0})
    restarted.enforce_hang(job, 35, {PID: 0.0})
    assert kills == []
    restarted.enforce_hang(job, 40, {PID: 0.0})
    assert kills == [(999999, 15)]
    assert restarted.queue.read("test-ticket")["stopped"] == 40


def test_slot_ignores_timeout_file_and_stays_running(queue, buildq, monkeypatch):
    runner, kills = queue
    runner.write("test-ticket", {"kind": "slot", "tool": "swift", "started": 1})
    (runner.q.parent / "slot-timeout").write_text("1\n")
    clock = SimpleNamespace(time=lambda: 0)
    monkeypatch.setattr(buildq, "time", clock)
    monkeypatch.setattr(buildq, "ps_command", lambda pid: "swift test")
    for now in range(600, 60001, 600):
        clock.time = lambda: now
        runner.reconcile()
    assert kills == []
    saved = runner.queue.read("test-ticket")
    assert saved["state"] == "running"
    assert "stopped" not in saved


def test_spawn_does_not_add_timeout(queue, monkeypatch):
    runner, _ = queue
    job = runner.jobs["test-ticket"]
    job["test_flags"] = ["--cached"]
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kwargs: calls.append(argv))
    runner.spawn(job)
    assert calls == [["zone-tool", "test", "--cached", "--", "swift", "test"]]


def test_old_timeout_api_is_removed(buildq):
    assert not hasattr(buildq, "DEFAULT_TIMEOUT")
    assert not hasattr(buildq, "timeout_of")
    assert not hasattr(buildq.Runner, "enforce_slot_timeout")


@pytest.mark.parametrize("wait_lines", [0, 1, 6])
def test_answered_skips_leading_single_wait_lines(queue, wait_lines):
    runner, _ = queue
    wait = "zone-test: a run is already going in this worktree; waiting for its result\n"
    answer = "zone-test: PASS at 12:00 already recorded for this exact code; not run again\n"
    (runner.q / "test-ticket.log").write_text(wait * wait_lines + answer)

    assert runner.answered(runner.jobs["test-ticket"]) is True


def test_answered_rejects_non_wait_output_before_answer(queue):
    runner, _ = queue
    (runner.q / "test-ticket.log").write_text(
        "zone-test: a run is already going in this worktree; waiting for its result\n"
        "test output\n"
        "zone-test: PASS at 12:00 already recorded for this exact code; not run again\n"
    )

    assert runner.answered(runner.jobs["test-ticket"]) is False


def test_answered_rejects_empty_log(queue):
    runner, _ = queue
    (runner.q / "test-ticket.log").write_text("")

    assert runner.answered(runner.jobs["test-ticket"]) is False


def test_single_wait_output_keeps_idle_run_alive_past_backstop(queue):
    runner, kills = queue
    job = runner.jobs["test-ticket"]
    log = runner.q / "test-ticket.log"
    for step in range(81):
        with log.open("a") as output:
            output.write("zone-test: a run is already going in this worktree; waiting for its result\n")
        runner.enforce_hang(job, step * 2.5, {PID: 0.0})

    assert kills == []
    assert "stopped" not in runner.queue.read("test-ticket")


def test_backstop_ignores_runner_environment_when_job_omits_window(queue, monkeypatch):
    runner, kills = queue
    monkeypatch.setenv("CODETEAM_HANG_WINDOW", "1")
    runner.write("test-ticket", {"env": {"CODETEAM_HANG_CPU_PCT": "1"}})
    job = runner.jobs["test-ticket"]
    runner.enforce_hang(job, 0, {PID: 0.0})
    runner.enforce_hang(job, 10, {PID: 0.0})
    assert kills == []
    assert "stopped" not in runner.queue.read("test-ticket")

    for now in range(50, 1200, 50):
        runner.enforce_hang(job, now, {PID: 0.0})
        assert kills == []
        assert "stopped" not in runner.queue.read("test-ticket")

    runner.enforce_hang(job, 1200, {PID: 0.0})
    assert kills == [(999999, 15)]
    saved = runner.queue.read("test-ticket")
    assert saved["stopped"] == 1200
    assert saved["reason"].startswith("hung:")
