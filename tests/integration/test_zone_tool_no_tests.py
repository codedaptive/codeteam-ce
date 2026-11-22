import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("CODETEAM_TEST_GROUP", "unit") != "integration", reason="integration group only")
HOME = Path(__file__).resolve().parents[2]
ZONE_TOOL = HOME / "bin" / "zone-tool"


@pytest.fixture
def scratch(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n")
    (repo / "test_sample.py").write_text("def test_passes():\n    assert True\n")
    (repo / "docs").mkdir()
    (repo / "docs" / "README").write_text("no tests here\n")
    for args in (["init", "-q"], ["add", "."], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "start"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    stub = tmp_path / "stub"
    stub.mkdir()
    tmutil = stub / "tmutil"
    tmutil.write_text("#!/bin/sh\nexit 0\n")
    tmutil.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CODETEAM_", "HERDR_", "ZONE_")) and k not in
           {"MAKEFLAGS", "MFLAGS", "MAKELEVEL", "MAKEOVERRIDES", "MAKEFILES", "DIR", "PYTHONPATH", "GROUP"}}
    env.update(CODETEAM_HOME=str(HOME), CODETEAM_QUEUE_DIR=str(tmp_path / "queue"),
               CODETEAM_BUILDQ="/nonexistent", CODETEAM_BUILDQ_LAUNCH=str(HOME / "zone" / "tests" / "fake-launchctl"),
               GIT_CEILING_DIRECTORIES=str(tmp_path), PYTHONDONTWRITEBYTECODE="1",
               PATH=f"{stub}{os.pathsep}{env['PATH']}")
    return repo, env


def run_tool(scratch, *args):
    repo, env = scratch
    return subprocess.run([sys.executable, str(ZONE_TOOL), *args], cwd=repo, env=env,
                          capture_output=True, text=True, timeout=600)


def run_one(scratch, path):
    return run_tool(scratch, "test", "--key", "k", "--", sys.executable, str(ZONE_TOOL), "test-one", path)


def record(scratch):
    (path,) = scratch[0].glob(".test-record-*.json")
    return json.loads(path.read_text())


def test_empty_test_one_records_no_tests(scratch):
    run = run_one(scratch, "docs")
    assert run.returncode == 0, (run.stdout, run.stderr)
    assert record(scratch)["result"] == "NO TESTS"


def test_pytest_collecting_nothing_records_no_tests(scratch):
    (scratch[0] / "test_nothing.py").write_text("# No tests to collect.\n")
    run = run_one(scratch, "test_nothing.py")
    assert run.returncode == 0, (run.stdout, run.stderr)
    assert any(line.startswith("test-one: run ") and "-m pytest" in line and "test_nothing.py" in line
               for line in run.stdout.splitlines()), run.stdout
    assert "test-one: test_nothing.py: no tests" in run.stdout
    assert record(scratch)["result"] == "NO TESTS"


def test_status_reports_no_tests_and_succeeds(scratch):
    run = run_one(scratch, "docs")
    assert run.returncode == 0, (run.stdout, run.stderr)
    status = run_tool(scratch, "test-status")
    assert status.returncode == 0, (status.stdout, status.stderr)
    assert any(line.startswith("NO TESTS") for line in status.stdout.splitlines()), status.stdout


def test_passing_pytest_records_pass(scratch):
    run = run_one(scratch, "test_sample.py")
    assert run.returncode == 0, (run.stdout, run.stderr)
    assert record(scratch)["result"] == "PASS"


def test_covered_reports_no_tests_without_claiming_pass(scratch):
    run = run_one(scratch, "docs")
    assert run.returncode == 0, (run.stdout, run.stderr)
    covered = run_tool(scratch, "covered")
    assert covered.returncode == 0, (covered.stdout, covered.stderr)
    assert "NO TESTS" in covered.stdout
    assert "PASS" not in covered.stdout
