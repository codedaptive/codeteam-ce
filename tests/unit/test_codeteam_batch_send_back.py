import contextlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_batch_send_back import batch_send_back


def test_send_back_removes_queue_records_saved_rows_and_notifies_first_zone(tmp_path):
    path = tmp_path / "entry.json"
    entry = {"tips": [["a", "ta"], ["b", "tb"]]}
    path.write_text(json.dumps(entry))
    records = {"a": {"wo": "a", "zone": "alpha", "queued": "now", "stage2": []},
               "b": {"wo": "b", "zone": "beta", "queued": "now", "stage2": [{"step": "old"}]}}
    team = SimpleNamespace(integration="integration", wo=lambda wo: records[wo], save_wo=Mock(),
                           notify=Mock(), log=Mock())
    land = SimpleNamespace(Lock=lambda team_: contextlib.nullcontext(), entry_members=lambda e: e["tips"],
                           zone_session=lambda team_, zone: "Coord-" + zone, now=lambda: "time",
                           integration_send_back=Mock(return_value="request"))
    run = {"commit": "1234567890abcdef", "rows": [{"step": "failed", "kept": "batch"}],
           "results": [{"name": "test", "outcome": "FAIL"}]}
    frames = [["src/a.py", 4]]
    assert batch_send_back(team, land, (path, entry), run, frames) is None
    assert not path.exists()
    assert all("queued" not in record for record in records.values())
    assert records["a"]["stage2"] == [{"step": "failed", "kept": "batch"}]
    assert records["b"]["stage2"] == [{"step": "old"}, {"step": "failed", "kept": "batch"}]
    land.integration_send_back.assert_called_once_with(["a", "b"], "integration", "1234567890abcdef",
                                                       run["results"], frames)
    team.notify.assert_called_once_with("Coord-alpha", "REQUEST", "request")
    team.log.assert_called_once_with({"time": "time", "wos": ["a", "b"], "result": "integration failed"})
