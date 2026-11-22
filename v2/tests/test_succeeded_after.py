import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def assistant(timestamp, model="claude-opus-5-5", **fields):
    return {"type": "assistant", "timestamp": timestamp, "message": {"model": model, "content": []}, **fields}


def test_returns_newest_success_even_out_of_file_order():
    from codeteam2.succeeded_after import succeeded_after
    records = [assistant("2024-01-01T00:00:20Z"), assistant("2024-01-01T00:00:10Z")]
    assert succeeded_after(records, 1704067200.0) == 1704067220.0


def test_success_must_be_strictly_after_cutoff():
    from codeteam2.succeeded_after import succeeded_after
    assert succeeded_after([assistant("2024-01-01T00:00:00Z")], 1704067200.0) is None


def test_synthetic_and_api_error_records_are_not_successes():
    from codeteam2.succeeded_after import succeeded_after
    records = [assistant("2024-01-01T00:00:10Z", "<synthetic>"),
               assistant("2024-01-01T00:00:20Z", isApiErrorMessage=True)]
    assert succeeded_after(records, 1704067200.0) is None


def test_non_assistant_and_model_less_records_are_not_successes():
    from codeteam2.succeeded_after import succeeded_after
    records = [{"type": "user", "timestamp": "2024-01-01T00:00:10Z", "message": {"model": "claude-opus-5-5"}},
               {"type": "assistant", "timestamp": "2024-01-01T00:00:20Z", "message": {}}]
    assert succeeded_after(records, 1704067200.0) is None
