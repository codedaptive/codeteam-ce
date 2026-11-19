import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_record_paths import record_paths


def test_summary_paths_keep_order_and_deduplicate_all_verdicts():
    text = ("zone-test: PASS (exit 0); record /p/.test-record-a.json\n"
            "zone-test: FAIL (exit 1); record /p/.test-record-b.json\n"
            "zone-test: HUNG (exit 124); record /p/.test-record-c.json\n"
            "zone-test: BROKEN (exit 3); record /p/.test-record-d.json\n"
            "zone-test: PASS (exit 0); record /p/.test-record-a.json\n")
    assert record_paths(text) == ["/p/.test-record-a.json", "/p/.test-record-b.json",
                                  "/p/.test-record-c.json", "/p/.test-record-d.json"]


def test_no_tests_summary_record_path():
    assert record_paths("zone-test: NO TESTS (exit 0); record /x/.test-record-ab.json\n") == [
        "/x/.test-record-ab.json"
    ]


def test_non_summary_record_mentions_are_ignored():
    assert record_paths("log: record /p/.test-record-a.json\nall passed\n") == []
