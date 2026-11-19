#!/usr/bin/env -S python3 -u
"""A promote restarts the runners of the program it changed, wherever their manifests live:
a v5.5 checkout's promotes run production's codeteam-land, sprocket's runners run the fork's, and before this the
fork's promotes restarted nothing, so sprocket's runners kept the fork's code of 11-15 11:58.
Zone integration: codeteam-land's after_promote with the real share/codeteam_runner_jobs.py, both the zone
lane's files, on real launchd job files and manifests in a temp home."""
import importlib.machinery
import importlib.util
import os
import plistlib
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("CODETEAM_TEST_GROUP", "unit") != "integration",
                                reason="integration group only; run with CODETEAM_TEST_GROUP=integration")

ROOT = Path(__file__).resolve().parents[3]
loader = importlib.machinery.SourceFileLoader("cl_promote_restarts", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)

OLD, TIP = "a" * 40, "0123456789abcdef0123456789abcdef01234567"
COMMANDS = {"queue-run": "com.codeteam.codeteam-land", "recheck-run": "com.codeteam.codeteam-recheck",
            "validate-run": "com.codeteam.codeteam-validate"}


def checkout(path):
    (path / "bin").mkdir(parents=True)
    (path / "bin" / "codeteam-land").touch()
    (path / "teams").mkdir()
    return path


def team(home, repo, name, program):
    """A team whose manifest is in repo's teams/ and whose three runners run program."""
    manifest = repo / "teams" / f"{name}.toml"
    manifest.write_text(f'repo = "{repo}"\nworktree_root = "{home / f"team-{name}"}"\n[land]\norchestrator = "Orc"\n')
    agents = home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    for command, label in COMMANDS.items():
        (agents / f"{label}.{name}.plist").write_bytes(plistlib.dumps({"Label": f"{label}.{name}", "ProgramArguments": [
            "python3", str(program), str(manifest), command]}))
    target = cl.Team(str(manifest), create=False)
    target.notify = Mock()
    return target


def restarts(target):
    return sorted(path.name for path in (target.dir / "restart").glob("*.json"))


@pytest.fixture
def fleet(tmp_path):
    production, fork = checkout(tmp_path / "codeteam"), checkout(tmp_path / "other-checkout")
    teams = {"codeteam": team(tmp_path, production, "codeteam", production / "bin" / "codeteam-land"),
             "other-checkout": team(tmp_path, fork, "other-checkout", production / "bin" / "codeteam-land"),
             "sprocket": team(tmp_path, fork, "sprocket", fork / "bin" / "codeteam-land")}
    with patch.object(Path, "home", return_value=tmp_path), patch.object(cl, "HERE", production / "bin"), \
            patch.object(cl, "out", return_value="bin/codeteam-land\n"):
        yield teams


def test_the_fork_s_promote_restarts_sprocket_s_runners_and_not_its_own(fleet):
    cl.after_promote(fleet["other-checkout"], OLD, TIP)
    assert restarts(fleet["sprocket"]) == ["queue-run.json", "recheck-run.json", "validate-run.json"]
    assert restarts(fleet["other-checkout"]) == restarts(fleet["codeteam"]) == []


def test_production_s_promote_restarts_the_fork_team_s_runners_and_not_sprocket_s(fleet):
    cl.after_promote(fleet["codeteam"], OLD, TIP)
    expected = ["queue-run.json", "recheck-run.json", "validate-run.json"]
    assert restarts(fleet["codeteam"]) == restarts(fleet["other-checkout"]) == expected
    assert restarts(fleet["sprocket"]) == []
