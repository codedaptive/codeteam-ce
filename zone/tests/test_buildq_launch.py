import importlib.machinery
import importlib.util
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(params=["zone-tool", "codeteam-slot"])
def client(request, monkeypatch):
    name = request.param.replace("-", "_")
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / "bin" / request.param))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    monkeypatch.delenv("CODETEAM_BUILDQ_LAUNCH", raising=False)
    monkeypatch.delenv("CODETEAM_QUEUE_DIR", raising=False)
    return module


class OSProxy:
    def __init__(self, realpath=None):
        self.path = PathProxy(realpath)

    def __getattr__(self, name):
        if name == "getuid":
            return lambda: 501
        if name == "access":
            return lambda *args: True
        return getattr(os, name)


class PathProxy:
    def __init__(self, realpath):
        self._realpath = realpath

    def __getattr__(self, name):
        if name == "realpath" and self._realpath is not None:
            return self._realpath
        return getattr(os.path, name)


@pytest.fixture
def launch(monkeypatch, client):
    state = SimpleNamespace(calls=[], rc=0, stderr="", error=None)

    def run(args, **kwargs):
        state.calls.append((args, kwargs))
        if state.error:
            raise state.error
        return subprocess.CompletedProcess(args, state.rc, "", state.stderr)

    def no_popen(*args, **kwargs):
        raise AssertionError("runner must not be spawned with Popen")

    monkeypatch.setattr(client, "subprocess", SimpleNamespace(run=run, Popen=no_popen))
    monkeypatch.setattr(client, "os", OSProxy())
    return state


def test_buildq_label(client):
    assert client.BUILDQ_LABEL == "com.codeteam.codeteam-buildq"


def test_buildq_live_queue(client):
    assert client.BUILDQ_LIVE_QUEUE == str(ROOT / "run" / "queue")


def test_live_queue_kickstarts_launchd(client, launch, monkeypatch, tmp_path):
    q = tmp_path / "queue"
    live = client.BUILDQ_LIVE_QUEUE
    monkeypatch.setattr(client, "os", OSProxy(lambda path: live if str(path) == str(q) else str(path)))

    assert client.start_runner(q) is None
    assert len(launch.calls) == 1
    args, kwargs = launch.calls[0]
    assert args == ["/bin/launchctl", "kickstart", "gui/501/com.codeteam.codeteam-buildq"]
    assert kwargs["env"]["CODETEAM_QUEUE_DIR"] == str(q)
    assert kwargs["env"]["CODETEAM_BUILDQ_LOG"] == str(q.parent / "buildq.log")
    assert kwargs["cwd"] == "/"


def test_scratch_queue_without_override_is_refused(client, launch, tmp_path):
    q = tmp_path / "queue"
    reason = client.start_runner(q)

    assert launch.calls == []
    assert str(q) in reason
    assert client.BUILDQ_LIVE_QUEUE in reason
    assert "com.codeteam.codeteam-buildq" in reason
    assert "CODETEAM_BUILDQ_LAUNCH" in reason


def test_override_kickstarts_scratch_queue(client, launch, monkeypatch, tmp_path):
    monkeypatch.setenv("CODETEAM_BUILDQ_LAUNCH", "/x/fake-launchctl")

    assert client.start_runner(tmp_path / "queue") is None
    assert len(launch.calls) == 1
    assert launch.calls[0][0] == ["/x/fake-launchctl", "kickstart", "gui/501/com.codeteam.codeteam-buildq"]


def test_missing_launchd_job_explains_bootstrap(client, launch, monkeypatch, tmp_path):
    monkeypatch.setenv("CODETEAM_BUILDQ_LAUNCH", "/x/fake-launchctl")
    launch.rc = 113
    launch.stderr = 'Could not find service "com.codeteam.codeteam-buildq" in domain for user gui: 501'

    reason = client.start_runner(tmp_path / "queue")

    assert "build-queue runner job com.codeteam.codeteam-buildq is not loaded in launchd" in reason
    assert "launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.codeteam.codeteam-buildq.plist" in reason


def test_other_launch_failure_is_not_reported_as_missing_job(client, launch, monkeypatch, tmp_path):
    monkeypatch.setenv("CODETEAM_BUILDQ_LAUNCH", "/x/fake-launchctl")
    launch.rc = 1
    launch.stderr = "Operation not permitted"

    reason = client.start_runner(tmp_path / "queue")

    assert "cannot start the runner" in reason
    assert "exited 1" in reason
    assert "Operation not permitted" in reason
    assert "not loaded" not in reason


def test_launch_oserror_is_reported(client, launch, monkeypatch, tmp_path):
    monkeypatch.setenv("CODETEAM_BUILDQ_LAUNCH", "/x/fake-launchctl")
    launch.error = OSError("boom")

    reason = client.start_runner(tmp_path / "queue")

    assert "cannot start the runner" in reason
    assert "boom" in reason


def test_slot_ensure_runner_raises_start_failure(monkeypatch, tmp_path):
    loader = importlib.machinery.SourceFileLoader("slot_ensure", str(ROOT / "bin" / "codeteam-slot"))
    spec = importlib.util.spec_from_loader("slot_ensure", loader)
    slot = importlib.util.module_from_spec(spec)
    loader.exec_module(slot)
    monkeypatch.setattr(slot, "runner_alive", lambda q: False)
    reason = "build-queue runner job com.codeteam.codeteam-buildq is not loaded in launchd"
    monkeypatch.setattr(slot, "start_runner", lambda q: reason, raising=False)
    def no_popen(*args, **kwargs):
        raise AssertionError("runner must not be spawned with Popen")

    monkeypatch.setattr(slot, "subprocess", SimpleNamespace(Popen=no_popen))

    with pytest.raises(slot.QueueUnavailable) as exc:
        slot.ensure_runner(tmp_path / "queue")
    assert reason in str(exc.value)
