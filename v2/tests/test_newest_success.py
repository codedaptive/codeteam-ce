import json
import os
import sys
from pathlib import Path

from conftest import integration_module

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
pytestmark = integration_module

def plant(path, timestamp, mtime):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "assistant", "timestamp": timestamp,
                                "message": {"model": "gpt-6.1-sol(high)", "content": []}}) + "\n")
    os.utime(path, (mtime, mtime))


def test_newest_success_scans_main_and_subagent_transcripts(tmp_path):
    from codeteam2.newest_success import newest_success
    plant(tmp_path / "one" / "main.jsonl", "2024-01-01T00:00:10Z", 1704067250)
    plant(tmp_path / "two" / "sid" / "subagents" / "agent-a.jsonl", "2024-01-01T00:00:20Z", 1704067240)
    assert newest_success(1704067200, tmp_path) == 1704067220.0


def test_newest_success_finds_nested_workflow_agent_answer(tmp_path):
    from codeteam2.newest_success import newest_success
    plant(tmp_path / "project" / "sid" / "subagents" / "workflows" / "wf_x" / "agent-y.jsonl",
          "2024-01-01T00:00:20Z", 1704067240)
    assert newest_success(1704067200, tmp_path) == 1704067220.0


def test_newest_success_skips_files_not_modified_after_cutoff(tmp_path):
    from codeteam2.newest_success import newest_success
    plant(tmp_path / "one" / "old.jsonl", "2024-01-01T00:00:20Z", 1704067200)
    assert newest_success(1704067200, tmp_path) is None


def test_newest_success_obeys_newest_first_file_cap(tmp_path):
    from codeteam2.newest_success import newest_success
    plant(tmp_path / "one" / "older.jsonl", "2024-01-01T00:00:30Z", 1704067230)
    plant(tmp_path / "one" / "newer.jsonl", "2024-01-01T00:00:10Z", 1704067240)
    assert newest_success(1704067200, tmp_path, max_files=1) == 1704067210.0


def test_newest_success_without_qualifying_records_is_none(tmp_path):
    from codeteam2.newest_success import newest_success
    plant(tmp_path / "one" / "before.jsonl", "2023-12-31T23:59:59Z", 1704067240)
    assert newest_success(1704067200, tmp_path) is None
