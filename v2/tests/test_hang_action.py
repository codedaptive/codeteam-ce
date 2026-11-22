import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2.hang_action import hang_action


@pytest.mark.parametrize("model,wait,expected", [
    ("claude-opus-5-5", 299, None),
    ("claude-opus-5-5", 300, "nudge"),
    ("claude-opus-5-5", 301, "nudge"),
    ("gpt-6.1-sol(high)", 301, None),
    ("gpt-6.1-sol(high)", 721, "nudge"),
    ("unknown", 301, "nudge"),
])
def test_main_action_by_model_and_elapsed_time(model, wait, expected):
    assert hang_action("main", {"id": "req", "at": 1000, "model": model}, 1000 + wait) == expected


def test_manifest_override_delays_gpt_nudge():
    assert hang_action("main", {"id": "req", "at": 1000, "model": "gpt-6.1-sol(high)"},
                       1721, {"gpt": 900}) is None


def test_subagent_at_one_threshold_is_not_noted():
    assert hang_action("subagent", {"id": "req", "at": 1000, "model": "claude-opus-5-5"}, 1300) is None


def test_subagent_at_double_threshold_is_noted():
    assert hang_action("subagent", {"id": "req", "at": 1000, "model": "claude-opus-5-5"}, 1600) == "note"


def test_no_pending_request_has_no_action():
    assert hang_action("main", None, 2000) is None
