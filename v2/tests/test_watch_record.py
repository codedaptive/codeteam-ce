import json
import sys
from pathlib import Path

from conftest import integration_only

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2.watch_record import watch_record


@integration_only
def test_record_logs_and_appends_matching_sorted_json(tmp_path):
    logs = []
    fields = {"at": 1000, "session": "Coord-a", "agent": None, "agent_type": None,
              "model": "claude-opus-5-5", "wait_s": 301, "action": "esc+continue", "request": "req-1"}
    watch_record(tmp_path, logs.append, fields)
    assert logs == ['watchdog ' + json.dumps(fields, sort_keys=True)]
    assert (tmp_path / "watchdog.jsonl").read_text().splitlines() == [json.dumps(fields, sort_keys=True)]


@integration_only
def test_record_appends_one_line_per_action(tmp_path):
    logs = []
    watch_record(tmp_path, logs.append, {"request": "one", "action": "esc+continue"})
    watch_record(tmp_path, logs.append, {"request": "two", "action": "note parent"})
    assert [json.loads(line) for line in (tmp_path / "watchdog.jsonl").read_text().splitlines()] == [
        {"request": "one", "action": "esc+continue"}, {"request": "two", "action": "note parent"}]
    assert len(logs) == 2
