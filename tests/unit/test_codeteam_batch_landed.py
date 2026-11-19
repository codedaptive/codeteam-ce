import contextlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_batch_landed import batch_landed


def test_saved_batch_rows_are_appended_to_every_member_before_landing(tmp_path):
    path = tmp_path / "entry.json"
    entry = {"review": "land", "tips": [["a", "ta"], ["b", "tb"]]}
    path.write_text(json.dumps(entry))
    records = {wo: {"wo": wo, "stage2": [{"step": "old"}]} for wo in ("a", "b")}
    team = SimpleNamespace(wo=lambda wo: records[wo], save_wo=Mock())
    def land_entry(team_, path_):
        assert records["a"]["stage2"] == [{"step": "old"}, {"step": "batch", "kept": "batch-123"}]
        assert records["b"]["stage2"] == [{"step": "old"}, {"step": "batch", "kept": "batch-123"}]
        return 0
    land = SimpleNamespace(Lock=lambda team_: contextlib.nullcontext(),
                           entry_members=lambda e: e["tips"], land_entry=Mock(side_effect=land_entry), CONFLICT=2)
    assert batch_landed(team, land, [(path, entry)], {"rows": [{"step": "batch", "kept": "batch-123"}]}) is True
    assert team.save_wo.call_count == 2
    land.land_entry.assert_called_once_with(team, path)


@pytest.mark.parametrize("previous,batch,expected", [(960.0, 300, 960.0), (400.0, 1000, 1000.0), (None, 120, 120.0)])
def test_stage2_measure_is_maximum_saved_before_landing(tmp_path, previous, batch, expected):
    path = tmp_path / "entry.json"
    entry = {"review": "land", "tips": [["a", "ta"], ["b", "tb"]]}
    path.write_text(json.dumps(entry))
    records = {wo: {"wo": wo, **({"stage2_tests_s": previous} if previous is not None else {})}
               for wo in ("a", "b")}
    saved = []
    team = SimpleNamespace(wo=lambda wo: records[wo], save_wo=lambda rec: saved.append(dict(rec)))
    def land_entry(team_, path_):
        assert [(rec["wo"], rec.get("stage2_tests_s")) for rec in saved] == [("a", expected), ("b", expected)]
        return 0
    land = SimpleNamespace(Lock=lambda team_: contextlib.nullcontext(), entry_members=lambda e: e["tips"],
                           land_entry=Mock(side_effect=land_entry), CONFLICT=2)
    assert batch_landed(team, land, [(path, entry)], {"rows": [], "tests_s": batch}) is True


def test_held_entry_is_not_landed(tmp_path):
    path = tmp_path / "entry.json"
    entry = {"review": "land", "hold": True, "tips": [["a", "ta"]]}
    path.write_text(json.dumps(entry))
    team = SimpleNamespace(wo=lambda wo: {"wo": wo}, save_wo=Mock())
    land = SimpleNamespace(Lock=lambda team_: contextlib.nullcontext(), entry_members=lambda e: e["tips"],
                           land_entry=Mock(), CONFLICT=2)
    assert batch_landed(team, land, [(path, entry)], {"rows": []}) is True
    land.land_entry.assert_not_called()


def test_landing_refusal_returns_false(tmp_path):
    path = tmp_path / "entry.json"
    entry = {"review": "land", "tips": [["a", "ta"]]}
    path.write_text(json.dumps(entry))
    team = SimpleNamespace(wo=lambda wo: {"wo": wo}, save_wo=Mock())
    land = SimpleNamespace(Lock=lambda team_: contextlib.nullcontext(), entry_members=lambda e: e["tips"],
                           land_entry=Mock(return_value=5), CONFLICT=2)
    assert batch_landed(team, land, [(path, entry)], {"rows": []}) is False
