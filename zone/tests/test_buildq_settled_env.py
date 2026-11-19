import fcntl
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def buildq(monkeypatch):
    name = "codeteam_buildq_settled_env"
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / "bin" / "codeteam-buildq"))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    loader.exec_module(module)
    return module


def job(ticket, state):
    return {"ticket": ticket, "kind": "run", "class": "dev", "state": state,
            "key": "k", "command": [], "submitted": 1, "tool": "unused", "record": None,
            "env": {"JOBENV_FAKE": "x"}}


def put(q, value):
    (q / (value["ticket"] + ".json")).write_text(json.dumps(value))


def read(q, ticket):
    return json.loads((q / (ticket + ".json")).read_text())


@pytest.mark.parametrize("state", ["done", "broken"])
def test_runner_settle_writes_empty_env(buildq, tmp_path, state):
    value = job("T", "running")
    put(tmp_path, value)
    runner = buildq.Runner(tmp_path, tmp_path / "queue.toml")
    runner.settle(value, state, reason="example")
    saved = read(tmp_path, "T")
    assert saved["state"] == state
    assert saved["env"] == {}
    assert saved["reason"] == "example"
    assert saved["ticket"] == "T"


def test_queue_update_returns_and_writes_empty_settled_env(buildq, tmp_path):
    put(tmp_path, job("T", "running"))
    updated = buildq.Queue(tmp_path).update("T", {"state": "done"}, expect="running")
    assert updated["env"] == {}
    assert read(tmp_path, "T")["env"] == {}


def test_runner_start_keeps_running_env(buildq, tmp_path, monkeypatch):
    value = job("T", "queued")
    put(tmp_path, value)
    runner = buildq.Runner(tmp_path, tmp_path / "queue.toml")
    monkeypatch.setattr(runner, "spawn", lambda job: type("Child", (), {"pid": 123})())
    runner.start(value)
    saved = read(tmp_path, "T")
    assert saved["state"] == "running"
    assert saved["env"] == {"JOBENV_FAKE": "x"}


def test_once_startup_cleans_settled_records_before_tick_under_lock(buildq, tmp_path, monkeypatch):
    q = tmp_path / "queue"
    q.mkdir()
    for ticket, state in [("D", "done"), ("B", "broken"), ("Q", "queued")]:
        put(q, job(ticket, state))
    monkeypatch.setenv("CODETEAM_QUEUE_DIR", str(q))
    monkeypatch.setenv("CODETEAM_QUEUE_CONF", str(tmp_path / "queue.toml"))
    monkeypatch.setattr(buildq.os, "chdir", lambda path: None)
    held_locks = []
    take_lock = buildq.take_runner_lock

    def take(q, wait):
        lock = take_lock(q, wait)
        held_locks.append(lock)
        return lock

    observed = []

    def tick(runner):
        fd = os.open(q / ".runner.lock", os.O_RDWR)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = False
            except BlockingIOError:
                locked = True
            observed.append((locked, read(q, "D")["env"], read(q, "B")["env"], read(q, "Q")["env"]))
        finally:
            os.close(fd)
        return False

    monkeypatch.setattr(buildq, "take_runner_lock", take)
    monkeypatch.setattr(buildq.Runner, "tick", tick)
    try:
        assert buildq.main(["--once"]) == 0
    finally:
        for fd in held_locks:
            if fd is not None:
                os.close(fd)
    assert observed == [(True, {}, {}, {"JOBENV_FAKE": "x"})]
