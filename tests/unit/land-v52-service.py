#!/usr/bin/env -S python3 -u
"""Contracts for reinstalling the landing team's launchd services."""
import contextlib
import importlib.machinery
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ["CODETEAM_QUEUE_DIR"] = str(Path(tempfile.mkdtemp(prefix="land-queue-")) / "queue")
ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_service", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", stderr="", returncode=0)):
    loader.exec_module(cl)


class FakeLaunchctl:
    def __init__(self, loaded=None, bootstraps=None):
        self.loaded = dict(loaded or {})
        self.bootstraps = {label: list(results) for label, results in (bootstraps or {}).items()}
        self.events = []
        self.prints = {}

    def run(self, argv, **kwargs):
        assert argv[0] == "launchctl"
        self.events.append(("run", list(argv)))
        action = argv[1]
        label = Path(argv[-1]).stem if action == "bootstrap" else argv[-1].rsplit("/", 1)[-1]
        if action == "print":
            self.prints[label] = self.prints.get(label, 0) + 1
            assert self.prints[label] <= 300, "print polling did not stop at the bound"
            remaining = self.loaded.get(label, 0)
            self.loaded[label] = max(remaining - 1, 0)
            return SimpleNamespace(returncode=0 if remaining else 113, stdout="", stderr="")
        if action == "bootstrap":
            results = self.bootstraps.get(label, [])
            rc, stderr = results.pop(0) if results else (0, "")
            return SimpleNamespace(returncode=rc, stdout="", stderr=stderr)
        assert action == "bootout"
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def sleep(self, seconds):
        self.events.append(("sleep", seconds))


def make_team(root):
    repo = root / "repo"
    repo.mkdir()
    manifest = root / "sample.toml"
    manifest.write_text(f'repo = "{repo}"\nworktree_root = "{root / "team"}"\n'
                        '[land]\norchestrator = "Skippy"\n')
    return cl.Team(str(manifest))


def test_imports_launchd_from_own_checkout():
    with tempfile.TemporaryDirectory() as tmp:
        share = Path(tmp) / "share"
        share.mkdir()
        (share / "codeteam_launchd.py").write_text("DECOY = True\n")
        cwd = os.getcwd()
        try:
            os.chdir(tmp)
            with (patch.dict(sys.modules), patch.object(sys, "path", list(sys.path)),
                  patch.object(sys, "path_importer_cache", {})):
                sys.modules.pop("codeteam_launchd", None)
                loader = importlib.machinery.SourceFileLoader(
                    "cl_service_checkout_test", str(ROOT / "bin" / "codeteam-land"))
                spec = importlib.util.spec_from_loader(loader.name, loader)
                module = importlib.util.module_from_spec(spec)
                with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", stderr="", returncode=0)):
                    loader.exec_module(module)
                assert Path(module.codeteam_launchd.__file__).resolve() == ROOT / "share" / "codeteam_launchd.py"
                assert not hasattr(module.codeteam_launchd, "DECOY")
        finally:
            os.chdir(cwd)


def test_launchd_reinstall_delegates_to_shared_module():
    fake = FakeLaunchctl()
    run, sleep = fake.run, fake.sleep
    plist = Path("/tmp/sample.plist")
    result = cl.codeteam_launchd.ReinstallResult(False, "fake reason from shared module")
    with patch.object(cl.codeteam_launchd, "reinstall", return_value=result) as reinstall:
        reason = cl.launchd_reinstall("sample", plist, 501, run=run, sleep=sleep,
                                      wait_s=3.0, poll_s=0.5, retry_s=1.5)
    assert reason == "fake reason from shared module"
    reinstall.assert_called_once_with("sample", plist, 501, run=run, sleep=sleep,
                                      wait_s=3.0, poll_s=0.5, retry_s=1.5)


def test_waits_for_bootout_before_bootstrap():
    fake = FakeLaunchctl(loaded={"com.codeteam.codeteam-land.sample": 2})
    result = cl.launchd_reinstall("com.codeteam.codeteam-land.sample", Path("/tmp/sample.plist"), 501,
                                  run=fake.run, sleep=fake.sleep, poll_s=0.2)
    assert result is None
    assert fake.events == [
        ("run", ["launchctl", "bootout", "gui/501/com.codeteam.codeteam-land.sample"]),
        ("run", ["launchctl", "print", "gui/501/com.codeteam.codeteam-land.sample"]),
        ("sleep", 0.2),
        ("run", ["launchctl", "print", "gui/501/com.codeteam.codeteam-land.sample"]),
        ("sleep", 0.2),
        ("run", ["launchctl", "print", "gui/501/com.codeteam.codeteam-land.sample"]),
        ("run", ["launchctl", "bootstrap", "gui/501", "/tmp/sample.plist"]),
    ]


def test_bootstrap_error_retries_once_after_delay():
    fake = FakeLaunchctl(bootstraps={"sample": [(5, "Bootstrap failed: 5: Input/output error"), (0, "")]})
    result = cl.launchd_reinstall("sample", Path("/tmp/sample.plist"), 501,
                                  run=fake.run, sleep=fake.sleep, retry_s=2.0)
    assert result is None
    assert fake.events == [
        ("run", ["launchctl", "bootout", "gui/501/sample"]),
        ("run", ["launchctl", "print", "gui/501/sample"]),
        ("run", ["launchctl", "bootstrap", "gui/501", "/tmp/sample.plist"]),
        ("sleep", 2.0),
        ("run", ["launchctl", "bootstrap", "gui/501", "/tmp/sample.plist"]),
    ]


def test_install_continues_after_bootstrap_failure():
    error = "Bootstrap failed: 5: Input/output error"
    fake = FakeLaunchctl(bootstraps={"com.codeteam.codeteam-land.sample": [(5, error), (5, error)]})
    with tempfile.TemporaryDirectory() as tmp, patch.object(Path, "home", return_value=Path(tmp)):
        team = make_team(Path(tmp))
        (Path(tmp) / "Library/LaunchAgents").mkdir(parents=True)
        output = io.StringIO()
        code = None
        with patch.object(cl.subprocess, "run", side_effect=fake.run), patch.object(cl.time, "sleep", side_effect=fake.sleep), \
                patch.object(cl.os, "getuid", return_value=501), contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                cl.cmd_service(team, SimpleNamespace(action="install"))
            except SystemExit as exc:
                code = exc.code
        assert code == 1
        text = output.getvalue()
        assert any("com.codeteam.codeteam-land.sample" in line and "not installed" in line and error in line
                   for line in text.splitlines()), text
        assert "installed com.codeteam.codeteam-recheck.sample:" in text
        assert "installed com.codeteam.codeteam-validate.sample:" in text
        assert [Path(argv[-1]).stem for kind, argv in fake.events if kind == "run" and argv[1] == "bootstrap"] == [
            "com.codeteam.codeteam-land.sample", "com.codeteam.codeteam-land.sample",
            "com.codeteam.codeteam-recheck.sample", "com.codeteam.codeteam-validate.sample"]
        assert "com.codeteam.codeteam-land.sample" in text.splitlines()[-1]


def test_first_print_gone_bootstraps_without_sleep():
    fake = FakeLaunchctl()
    result = cl.launchd_reinstall("sample", Path("/tmp/sample.plist"), 501, run=fake.run, sleep=fake.sleep)
    assert result is None
    assert fake.events == [
        ("run", ["launchctl", "bootout", "gui/501/sample"]),
        ("run", ["launchctl", "print", "gui/501/sample"]),
        ("run", ["launchctl", "bootstrap", "gui/501", "/tmp/sample.plist"]),
    ]


def test_install_continues_when_job_still_loaded_at_bound():
    fake = FakeLaunchctl(loaded={"com.codeteam.codeteam-land.sample": 1000})
    with tempfile.TemporaryDirectory() as tmp, patch.object(Path, "home", return_value=Path(tmp)):
        team = make_team(Path(tmp))
        (Path(tmp) / "Library/LaunchAgents").mkdir(parents=True)
        output = io.StringIO()
        code = None
        with patch.object(cl.subprocess, "run", side_effect=fake.run), patch.object(cl.time, "sleep", side_effect=fake.sleep), \
                patch.object(cl.os, "getuid", return_value=501), contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                cl.cmd_service(team, SimpleNamespace(action="install"))
            except SystemExit as exc:
                code = exc.code
        assert code == 1
        assert 95 <= fake.prints["com.codeteam.codeteam-land.sample"] <= 105
        text = output.getvalue()
        assert any("com.codeteam.codeteam-land.sample" in line and "not installed" in line and "still loaded" in line
                   for line in text.splitlines()), text
        assert "installed com.codeteam.codeteam-recheck.sample:" in text
        assert "installed com.codeteam.codeteam-validate.sample:" in text
        assert [Path(argv[-1]).stem for kind, argv in fake.events if kind == "run" and argv[1] == "bootstrap"] == [
            "com.codeteam.codeteam-recheck.sample", "com.codeteam.codeteam-validate.sample"]
        assert "com.codeteam.codeteam-land.sample" in text.splitlines()[-1]


if __name__ == "__main__":
    tests = unittest.TestSuite(unittest.FunctionTestCase(value, description=name)
                               for name, value in list(globals().items()) if name.startswith("test_"))
    result = unittest.TextTestRunner(verbosity=2).run(tests)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("all passed")
