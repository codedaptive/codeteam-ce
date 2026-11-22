import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2.threshold_s import threshold_s


def test_claude_prefix_is_case_insensitive():
    assert threshold_s("CLAUDE-opus-5-5") == 300


def test_gpt_default():
    assert threshold_s("gpt-6.1-sol(high)") == 720


def test_unknown_model_uses_claude_threshold():
    assert threshold_s("unrecognized") == 300


def test_manifest_override_changes_gpt_threshold():
    assert threshold_s("gpt-6.1-sol(high)", {"gpt": 900}) == 900


def test_longest_case_insensitive_prefix_wins():
    assert threshold_s("GPT-6.1-sol(high)", {"GPT-6.1": 850, "gpt": 900}) == 850


def test_unknown_model_uses_overridden_claude_threshold():
    assert threshold_s("other", {"claude": 410}) == 410
