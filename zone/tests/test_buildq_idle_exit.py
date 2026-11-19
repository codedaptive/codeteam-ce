"""ZUT for codeteam-buildq's idle exit (D506): `release_when_idle` lets go of Q/.runner.lock first, then lists the
queue once more, so a job whose client saw the lock held just before the exit is never left queued with no runner.
The queue is a fake with `all()`; the lock is a real flock on a file in tmp_path."""
import fcntl
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def buildq(monkeypatch):
    name = "codeteam_buildq"
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / "bin" / "codeteam-buildq"))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    loader.exec_module(module)
    return module


def held(q: Path) -> bool:
    """Whether some open file description holds Q/.runner.lock, probed as zone-tool's runner_held does."""
    fd = os.open(q / ".runner.lock", os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(fd)
    return False


def queue_of(*states):
    return SimpleNamespace(all=lambda: [{"ticket": f"t{n}", "state": s} for n, s in enumerate(states)])


def test_an_idle_queue_releases_the_lock_and_exits(buildq, tmp_path):
    lock = buildq.take_runner_lock(tmp_path, False)
    assert held(tmp_path)
    assert buildq.release_when_idle(tmp_path, lock, queue_of("done", "broken")) is None
    assert not held(tmp_path)


def test_a_job_queued_after_the_tick_keeps_the_runner(buildq, tmp_path):
    lock = buildq.take_runner_lock(tmp_path, False)
    again = buildq.release_when_idle(tmp_path, lock, queue_of("done", "queued"))
    assert again is not None
    assert held(tmp_path)
    os.close(again)
    assert not held(tmp_path)


def test_a_running_job_keeps_the_runner(buildq, tmp_path):
    lock = buildq.take_runner_lock(tmp_path, False)
    again = buildq.release_when_idle(tmp_path, lock, queue_of("running"))
    assert again is not None
    os.close(again)


def test_the_lock_is_free_while_the_queue_is_listed(buildq, tmp_path):
    lock = buildq.take_runner_lock(tmp_path, False)
    seen = []
    listing = SimpleNamespace(all=lambda: seen.append(held(tmp_path)) or [])
    assert buildq.release_when_idle(tmp_path, lock, listing) is None
    assert seen == [False]


def test_a_new_runner_that_took_the_lock_first_wins(buildq, tmp_path, monkeypatch):
    lock = buildq.take_runner_lock(tmp_path, False)
    asked = []
    monkeypatch.setattr(buildq, "take_runner_lock", lambda q, wait: asked.append((q, wait)))
    assert buildq.release_when_idle(tmp_path, lock, queue_of("queued")) is None
    assert asked == [(tmp_path, False)]
