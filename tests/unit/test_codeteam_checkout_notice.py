import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_checkout_notice import checkout_notice


def test_first_failure_writes_marker_and_notifies_once_with_work_orders_and_error(tmp_path):
    sent = []
    marker = tmp_path / "queue-batch-checkout.json"
    assert checkout_notice(marker, ["a", "b"], "0123456789abcdef", "fatal: index.lock exists\nretry",
                           "t1", sent.append) is True
    assert len(sent) == 1
    for expected in ("a, b", "0123456789", "fatal: index.lock exists retry", "Nothing landed", "stays queued"):
        assert expected in sent[0]
    assert json.loads(marker.read_text()) == {"time": "t1", "commit": "0123456789abcdef", "wos": ["a", "b"],
                                              "error": "fatal: index.lock exists\nretry"}


def test_existing_marker_sends_nothing_and_keeps_the_first_record(tmp_path):
    sent = []
    marker = tmp_path / "queue-batch-checkout.json"
    marker.write_text("first\n")
    assert checkout_notice(marker, ["a"], "c", "error", "t2", sent.append) is False
    assert sent == []
    assert marker.read_text() == "first\n"
