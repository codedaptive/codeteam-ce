import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2.pending_request import pending_request


REQUEST = {"type": "api-request", "id": "req-1", "timestamp": "2026-11-19T00:00:00Z",
           "params": {"model": "claude-opus-5-5"}}


def test_request_returns_id_epoch_and_model():
    assert pending_request([REQUEST]) == {"id": "req-1", "at": 1795046400.0, "model": "claude-opus-5-5"}


def test_answered_request_is_not_pending():
    assert pending_request([REQUEST, {"type": "assistant", "requestRef": "req-1", "message": {"content": []}}]) is None


def test_tool_use_is_not_pending():
    assert pending_request([REQUEST, {"type": "assistant", "requestRef": "req-1",
                                      "message": {"content": [{"type": "tool_use", "id": "tool-1", "name": "Bash"}]}}]) is None


def test_turn_duration_ends_pending_request():
    assert pending_request([REQUEST, {"type": "system", "subtype": "turn_duration"}]) is None


def test_api_error_without_request_ref_ends_pending_request():
    assert pending_request([REQUEST, {"type": "assistant", "isApiErrorMessage": True,
                                      "error": "rate_limit", "message": {"model": "<synthetic>"}}]) is None


def test_user_interrupt_ends_pending_request():
    assert pending_request([REQUEST, {"type": "user", "message": {"content": "interrupted"}}]) is None


def test_neutral_records_leave_request_pending():
    records = [REQUEST, {"type": "api-request-blob"}, {"type": "attachment"},
               {"type": "progress"}, {"type": "api-request-shape"}]
    assert pending_request(records) == {"id": "req-1", "at": 1795046400.0, "model": "claude-opus-5-5"}


def test_last_request_after_answer_is_pending():
    second = {"type": "api-request", "id": "req-2", "timestamp": "2026-11-19T00:01:00Z",
              "params": {"model": "gpt-6.1-sol(high)"}}
    assert pending_request([REQUEST, {"type": "assistant", "requestRef": "req-1"}, second]) == {
        "id": "req-2", "at": 1795046460.0, "model": "gpt-6.1-sol(high)"}


def test_empty_transcript_has_no_request():
    assert pending_request([]) is None
