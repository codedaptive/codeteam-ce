"""Unit tests for launch environment composition."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2.launch_env import launch_env


def test_empty_inputs_return_retry_defaults():
    assert launch_env({}, {}) == {
        "CLAUDE_CODE_MAX_RETRIES": "4",
        "CLAUDE_CODE_RETRY_WATCHDOG_MAX_WAIT_MS": "180000",
        "CLAUDE_CODE_RETRY_WATCHDOG_MAX_USAGE_LIMIT_WAIT_MS": "180000",
        "CLAUDE_CODE_RETRY_WATCHDOG_SCOPE": "capacity",
    }


def test_manifest_value_overrides_retry_default():
    assert launch_env({}, {"CLAUDE_CODE_MAX_RETRIES": "9"})["CLAUDE_CODE_MAX_RETRIES"] == "9"


def test_retry_value_overrides_session_default_and_preserves_unrelated_default():
    result = launch_env({"CLAUDE_CODE_MAX_RETRIES": "2", "OTHER": "kept"}, {})
    assert result["CLAUDE_CODE_MAX_RETRIES"] == "4"
    assert result["OTHER"] == "kept"


def test_empty_inputs_do_not_add_api_timeout():
    assert "API_TIMEOUT_MS" not in launch_env({}, {})


def test_inputs_are_not_mutated():
    session = {"CLAUDE_CODE_MAX_RETRIES": "2", "SESSION_ONLY": "session"}
    manifest = {"CLAUDE_CODE_MAX_RETRIES": "9", "MANIFEST_ONLY": "manifest"}
    launch_env(session, manifest)
    assert session == {"CLAUDE_CODE_MAX_RETRIES": "2", "SESSION_ONLY": "session"}
    assert manifest == {"CLAUDE_CODE_MAX_RETRIES": "9", "MANIFEST_ONLY": "manifest"}


def test_result_is_a_new_dict():
    session = {"SESSION_ONLY": "session"}
    manifest = {"MANIFEST_ONLY": "manifest"}
    result = launch_env(session, manifest)
    assert result is not session
    assert result is not manifest


def test_values_are_not_expanded():
    result = launch_env({"SESSION_VALUE": "$HOME"}, {"MANIFEST_VALUE": "${HOME}/work"})
    assert result["SESSION_VALUE"] == "$HOME"
    assert result["MANIFEST_VALUE"] == "${HOME}/work"
