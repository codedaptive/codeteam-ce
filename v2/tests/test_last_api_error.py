import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def error(kind="overloaded"):
    return {"type": "assistant", "isApiErrorMessage": True, "error": kind,
            "uuid": "error-1", "timestamp": "2024-01-01T00:00:00.000Z",
            "message": {"model": "<synthetic>", "content": []}}


@pytest.mark.parametrize("kind", ["rate_limit", "overloaded", "authentication_failed", "billing_error"])
def test_recoverable_error_is_returned(kind):
    from codeteam2.last_api_error import last_api_error
    assert last_api_error([error(kind)]) == (kind, 1704067200.0, "error-1")


@pytest.mark.parametrize("kind", ["server_error", "invalid_request"])
def test_nonrecoverable_error_is_ignored(kind):
    from codeteam2.last_api_error import last_api_error
    assert last_api_error([error(kind)]) is None


def test_later_user_prompt_ends_error_episode():
    from codeteam2.last_api_error import last_api_error
    assert last_api_error([error(), {"type": "user", "message": {"content": "retry"}}]) is None


def test_neutral_records_do_not_hide_error():
    from codeteam2.last_api_error import last_api_error
    assert last_api_error([error(), {"type": "system"}, {"type": "progress"}]) == (
        "overloaded", 1704067200.0, "error-1")


def test_normal_assistant_record_is_not_an_error():
    from codeteam2.last_api_error import last_api_error
    assert last_api_error([error(), {"type": "assistant", "message": {"model": "claude-opus-5-5"}}]) is None
