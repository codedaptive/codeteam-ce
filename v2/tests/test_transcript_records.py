import json
import sys
from pathlib import Path

from conftest import integration_only

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2.transcript_records import transcript_records


@integration_only
def test_records_are_parsed_in_file_order_and_bad_lines_skipped(tmp_path):
    path = tmp_path / "transcript.jsonl"
    path.write_text('{"type":"api-request","id":"one"}\nnot json\n'
                    '{"type":"attachment"}\n{"type":"assistant","requestRef":"one"}\n')
    assert transcript_records(path) == [
        {"type": "api-request", "id": "one"}, {"type": "attachment"},
        {"type": "assistant", "requestRef": "one"}]


@integration_only
def test_unreadable_file_returns_empty_list(tmp_path):
    assert transcript_records(tmp_path / "missing.jsonl") == []


@integration_only
def test_tail_skips_partial_first_line(tmp_path):
    path = tmp_path / "transcript.jsonl"
    path.write_text(json.dumps({"type": "user", "content": "x" * 100}) + '\n{"type":"attachment"}\n')
    assert transcript_records(path, tail=40) == [{"type": "attachment"}]
