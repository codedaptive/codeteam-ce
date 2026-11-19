import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_integration_send_back import integration_send_back


def test_request_names_work_orders_commit_failures_and_logs_but_not_passes():
    results = [{"name": "compile good", "outcome": "PASS", "failing": [], "log": "/logs/good"},
               {"name": "tests api", "outcome": "FAIL", "failing": ["test_one", "test_two"], "log": "/logs/api"},
               {"name": "rits ui", "outcome": "FAIL", "failing": ["test_three"], "log": "/logs/ui"}]
    message = integration_send_back(["wo-a", "wo-b"], "landing-branch", "1234567890abcdef", results, [])
    for expected in ("wo-a", "wo-b", "Stage 2's integration step failed", "landing-branch", "1234567890",
                     "tests api", "test_one", "test_two", "/logs/api", "rits ui", "test_three", "/logs/ui",
                     "Nothing of it landed", "its tree is kept", "run land again"):
        assert expected in message
    assert "compile good" not in message


def test_request_does_not_claim_batch_was_rerun_alone():
    args = (["wo-a"], "integration", "1234567890abcdef", [{"name": "tests A", "outcome": "FAIL"}])
    if "frames" in inspect.signature(integration_send_back).parameters:
        message = integration_send_back(*args, [])
    else:
        message = integration_send_back(*args)
    assert "and then alone" not in message


def test_incomplete_callees_are_only_on_their_failing_step():
    results = [{"name": "tests api", "outcome": "FAIL", "failing": ["test_one", "test_two"],
                "callees_incomplete": ["test_one", "test_two"], "log": "/logs/api"},
               {"name": "rits ui", "outcome": "FAIL", "failing": ["test_three"], "log": "/logs/ui"}]
    message = integration_send_back(["wo-a"], "integration", "1234567890abcdef", results, [])
    failed = message.split(" Failed: ", 1)[1].split(". Nothing of it landed", 1)[0]
    first_step, second_step = failed.split("; rits ui (fail)", 1)
    assert "CodeGraph's callees were incomplete for test_one, test_two; matched on the stack alone" in first_step
    assert message.count("CodeGraph's callees were incomplete") == 1
    assert "CodeGraph's callees were incomplete" not in second_step
    assert "test_three" in second_step


def test_no_incomplete_callees_preserves_full_request():
    message = integration_send_back(["wo-a"], "integration", "1234567890abcdef",
                                    [{"name": "tests A", "outcome": "FAIL", "failing": ["test_bad"],
                                      "log": "/logs/fail"}], [["src/a.py", 12]])
    assert message == (
        "wo-a did not land: Stage 2's integration step failed at queue-run, tested on integration's "
        "tip with the queue's other ready work orders, at 1234567890. Its diff holds code on the failure's "
        "path: src/a.py:12. Failed: tests A (fail): failing tests test_bad; log /logs/fail. Nothing of it "
        "landed and it is out of the queue; its tree is kept. Fix it in the same work order tree and run land again."
    )


def test_request_names_matched_frames_and_diff():
    message = integration_send_back(["wo-a"], "integration", "1234567890abcdef",
                                    [{"name": "tests A", "outcome": "FAIL"}],
                                    [["src/a.py", 12], ["src/b.py", None]])
    assert "src/a.py:12" in message
    assert "src/b.py" in message
    assert "diff" in message and "failure" in message
