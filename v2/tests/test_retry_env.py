"""Retry defaults and their launch-script precedence."""
import shlex
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conftest import integration_only  # noqa: E402
from codeteam2.team import Session, Team, v1  # noqa: E402


def launch_exports(tmp_path, env=None, session_env=None):
    t = SimpleNamespace(
        isolate=False, m={}, home=tmp_path, root=tmp_path,
        team_file=tmp_path / "team.json", manifest="/m.toml", env=env or {},
        ledger=lambda n: tmp_path / "ledger" / n, compact_window_of=lambda n: None,
        effort_of=lambda n: None, lane_dir=lambda n: tmp_path,
        cmd=lambda v: f"codeteam {v}", expand=lambda v: v,
        scratchpad=lambda n: tmp_path / "scratch" / n,
    )
    team = object.__new__(Team)
    team.t = t
    team.cfg = {"mcp": False, "session_env": {"orc": session_env or {}}}
    team.product, team.retry_watchdog = "smoke", True
    team.dir = tmp_path / "v2"
    (team.dir / "launch").mkdir(parents=True, exist_ok=True)
    team.team_json = lambda: {"lanes": {}}
    session = Session("orc", "Orc-Test", "staff", "orc", tmp_path)
    team.session = lambda key: session
    team.ctx_env = lambda key, model: {}
    target = (tmp_path, "Orc-Test", "", tmp_path / "role.md", "", "")
    with patch.object(v1, "launch_target", return_value=target):
        path, _ = team.write_launch_script(session)
    exports = {}
    for line in path.read_text().splitlines():
        if line.startswith("export ") and "=" in line:
            name, value = line[len("export "):].split("=", 1)
            exports[name] = shlex.split(value)[0] if value else ""
    return exports


def test_retry_env_contains_contract_defaults():
    from codeteam2.retry_env import RETRY_ENV

    assert RETRY_ENV == {
        "CLAUDE_CODE_MAX_RETRIES": "4",
        "CLAUDE_CODE_RETRY_WATCHDOG_MAX_WAIT_MS": "180000",
        "CLAUDE_CODE_RETRY_WATCHDOG_MAX_USAGE_LIMIT_WAIT_MS": "180000",
        "CLAUDE_CODE_RETRY_WATCHDOG_SCOPE": "capacity",
    }


@integration_only
def test_launch_exports_retry_defaults(tmp_path):
    exports = launch_exports(tmp_path)
    assert {name: exports.get(name) for name in (
        "CLAUDE_CODE_MAX_RETRIES",
        "CLAUDE_CODE_RETRY_WATCHDOG_MAX_WAIT_MS",
        "CLAUDE_CODE_RETRY_WATCHDOG_MAX_USAGE_LIMIT_WAIT_MS",
        "CLAUDE_CODE_RETRY_WATCHDOG_SCOPE",
    )} == {
        "CLAUDE_CODE_MAX_RETRIES": "4",
        "CLAUDE_CODE_RETRY_WATCHDOG_MAX_WAIT_MS": "180000",
        "CLAUDE_CODE_RETRY_WATCHDOG_MAX_USAGE_LIMIT_WAIT_MS": "180000",
        "CLAUDE_CODE_RETRY_WATCHDOG_SCOPE": "capacity",
    }


@pytest.mark.parametrize("name,value", [
    ("CLAUDE_CODE_MAX_RETRIES", "7"),
    ("CLAUDE_CODE_RETRY_WATCHDOG_MAX_WAIT_MS", "123000"),
    ("CLAUDE_CODE_RETRY_WATCHDOG_MAX_USAGE_LIMIT_WAIT_MS", "456000"),
    ("CLAUDE_CODE_RETRY_WATCHDOG_SCOPE", "full"),
])
@integration_only
def test_manifest_env_overrides_retry_default(tmp_path, name, value):
    assert launch_exports(tmp_path, env={name: value})[name] == value


@pytest.mark.parametrize("name,manifest_value,session_value", [
    ("CLAUDE_CODE_MAX_RETRIES", "7", "2"),
    ("CLAUDE_CODE_RETRY_WATCHDOG_MAX_WAIT_MS", "123000", "1000"),
    ("CLAUDE_CODE_RETRY_WATCHDOG_MAX_USAGE_LIMIT_WAIT_MS", "456000", "2000"),
    ("CLAUDE_CODE_RETRY_WATCHDOG_SCOPE", "full", "capacity"),
])
@integration_only
def test_session_env_overrides_manifest_and_retry_default(tmp_path, name, manifest_value, session_value):
    exports = launch_exports(tmp_path, env={name: manifest_value}, session_env={name: session_value})
    assert exports[name] == session_value


@pytest.mark.parametrize("name", [
    "CLAUDE_CODE_MAX_RETRIES",
    "CLAUDE_CODE_RETRY_WATCHDOG_MAX_WAIT_MS",
    "CLAUDE_CODE_RETRY_WATCHDOG_MAX_USAGE_LIMIT_WAIT_MS",
    "CLAUDE_CODE_RETRY_WATCHDOG_SCOPE",
])
@integration_only
def test_empty_session_env_removes_retry_default_and_manifest_override(tmp_path, name):
    assert name in launch_exports(tmp_path)
    assert name not in launch_exports(tmp_path, session_env={name: ""})
    assert name not in launch_exports(tmp_path, env={name: "manifest"}, session_env={name: ""})


@integration_only
def test_launch_does_not_export_api_timeout(tmp_path):
    assert "API_TIMEOUT_MS" not in launch_exports(tmp_path)
