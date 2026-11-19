"""share/codeteam_run_planned.py alone (D526): each planned test runs by its kind from the repo root with the
children's environment, one ok or FAIL line each and the totals; pytest's exit 5 counts as neither. subprocess is a
fake; nothing runs. cmd_test_one with it: the zone-tool test-one tests (tests/unit/test_zone_tool_*.py).
"""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("codeteam_run_planned", ROOT / "share" / "codeteam_run_planned.py")
module = importlib.util.module_from_spec(spec)
dont_write_bytecode = sys.dont_write_bytecode
try:
    sys.dont_write_bytecode = True
    spec.loader.exec_module(module)
finally:
    sys.dont_write_bytecode = dont_write_bytecode

PYTEST = ["py3", "-m", "pytest", "-q"]
ENV = {"HOME": "/h"}


@pytest.fixture
def runs(monkeypatch):
    """codes: path -> exit code (default 0); calls: (cmd, cwd, env) per run."""
    f = SimpleNamespace(codes={}, calls=[])

    def run(cmd, cwd, env):
        f.calls.append((cmd, cwd, env))
        return SimpleNamespace(returncode=f.codes.get(cmd[-1], 0))

    monkeypatch.setattr(module, "subprocess", SimpleNamespace(run=run))
    return f


def test_each_kind_runs_its_own_command_from_the_root_with_the_env(runs, capsys):
    planned = [("py", "pkg"), ("script", "tests/unit/a.py"), ("sh", "tests/b.sh")]
    assert module.run_planned(planned, PYTEST, "py3", Path("/repo"), ENV, "pkg") == 0
    assert runs.calls == [(["py3", "-m", "pytest", "-q", "pkg"], Path("/repo"), ENV),
                          (["py3", "tests/unit/a.py"], Path("/repo"), ENV),
                          (["bash", "tests/b.sh"], Path("/repo"), ENV)]
    assert capsys.readouterr().out.splitlines() == [
        "test-one: run py3 -m pytest -q pkg", "ok   pkg",
        "test-one: run py3 tests/unit/a.py", "ok   tests/unit/a.py",
        "test-one: run bash tests/b.sh", "ok   tests/b.sh",
        "test-one: 3 passed, 0 failed"]


def test_a_failure_is_named_and_exits_1(runs, capsys):
    runs.codes = {"tests/b.sh": 3}
    assert module.run_planned([("sh", "tests/a.sh"), ("sh", "tests/b.sh")], PYTEST, "py3", Path("/r"), ENV, "t") == 1
    out = capsys.readouterr().out.splitlines()
    assert "FAIL tests/b.sh (exit 3)" in out
    assert out[-1] == "test-one: 1 passed, 1 failed: tests/b.sh"


def test_pytest_collecting_nothing_is_neither_pass_nor_fail(runs, capsys):
    runs.codes = {"empty": 5, "full": 0}
    assert module.run_planned([("py", "empty"), ("py", "full")], PYTEST, "py3", Path("/r"), ENV, "t") == 0
    assert capsys.readouterr().out.splitlines()[-1] == "test-one: 1 passed, 0 failed"


def test_exit_5_from_a_script_is_a_failure(runs, capsys):
    runs.codes = {"s.sh": 5}
    assert module.run_planned([("sh", "s.sh")], PYTEST, "py3", Path("/r"), ENV, "t") == 1
    assert capsys.readouterr().out.splitlines()[-1] == "test-one: 0 passed, 1 failed: s.sh"


@pytest.mark.parametrize("planned", [[], [("py", "empty")]])
def test_nothing_run_says_no_tests_and_exits_0(runs, capsys, planned):
    runs.codes = {"empty": 5}
    assert module.run_planned(planned, PYTEST, "py3", Path("/r"), ENV, "pkg") == 0
    assert capsys.readouterr().out.splitlines()[-1] == "test-one: pkg: no tests"
