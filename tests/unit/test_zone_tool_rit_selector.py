"""zone-tool test-one passes the RIT selector a calling zone's RIT step exports to the tests it runs (D525).

Children drop CODETEAM_* but a keep list, and the list lacked CODETEAM_RIT_SELECTOR, so a test that picks its RITs
by the selector (a conftest) never saw it (Orc-Codeteam-jj #4526).
"""

import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def zt():
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        loader = importlib.machinery.SourceFileLoader("zone_tool_rit_selector", str(ROOT / "bin" / "zone-tool"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = previous


def test_one_children_keep_the_rit_selector_and_drop_team_variables(zt, tmp_path, monkeypatch):
    (tmp_path / "pkg" / "tests").mkdir(parents=True)
    (tmp_path / "pkg" / "tests" / "test_a.py").write_text("def test_a(): pass\n")
    for name in ("CODETEAM_KINDS_BY_NAME", "GROUP", "CODETEAM_OWNS", "CODETEAM_TEST_GROUP"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CODETEAM_RIT_SELECTOR", "rit_")
    monkeypatch.setenv("CODETEAM_MANIFEST", "/live/team.toml")
    monkeypatch.setenv("ZONE_PYTHON", "fixed-python")
    monkeypatch.setattr(zt, "top", lambda: tmp_path)
    calls = []
    monkeypatch.setattr(zt.subprocess, "run",
                        lambda cmd, **kw: calls.append((cmd, kw["env"])) or SimpleNamespace(returncode=0))
    assert zt.cmd_test_one(["pkg"]) == 0
    [(cmd, env)] = calls
    assert cmd == ["fixed-python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "pkg"]
    assert env["CODETEAM_RIT_SELECTOR"] == "rit_"
    assert "CODETEAM_MANIFEST" not in env
