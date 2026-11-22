import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "share"))
loader = importlib.machinery.SourceFileLoader("cl_stage_records", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
loader.exec_module(cl)


def test_remove_dead_stages_keeps_live_and_invalid_records(tmp_path):
    from codeteam_remove_dead_stages import remove_dead_stages

    records = {"dead.json": '{"pid": 12}', "live.json": '{"pid": 34}',
               "truncated.json": '{"pid":', "array.json": '[]',
               "missing-pid.json": '{}', "string-pid.json": '{"pid": "12"}',
               "bool-pid.json": '{"pid": true}'}
    for name, text in records.items():
        (tmp_path / name).write_text(text)
    remove_dead_stages(tmp_path, lambda pid: pid == 34)
    assert not (tmp_path / "dead.json").exists()
    for name in records.keys() - {"dead.json"}:
        assert (tmp_path / name).read_text() == records[name]


def test_remove_dead_stages_skips_a_record_removed_during_scan(tmp_path, monkeypatch):
    from codeteam_remove_dead_stages import remove_dead_stages

    vanished = tmp_path / "gone.json"
    vanished.write_text('{"pid": 12}')
    (tmp_path / "dead.json").write_text('{"pid": 13}')
    read_text = Path.read_text

    def read(path, *args, **kwargs):
        if path == vanished:
            raise FileNotFoundError(path)
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    remove_dead_stages(tmp_path, lambda pid: False)
    assert not (tmp_path / "dead.json").exists()


@pytest.mark.parametrize("holds", [None, ("team", ["wo"])])
def test_stage_admission_skips_truncated_record(tmp_path, holds):
    stages = tmp_path / "restart" / "stages"
    stages.mkdir(parents=True)
    bad = stages / "bad.json"
    bad.write_text('{"pid":')
    error = None
    entered = False
    try:
        with cl.stage_admit("Stage 2", "check", qdir=tmp_path / "buildq", holds=holds):
            entered = True
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        error = exc
    assert error is None, f"admission raised {error!r}"
    assert entered
    assert bad.read_text() == '{"pid":'


def test_stage_holders_skips_truncated_record_during_admission(tmp_path):
    stages = tmp_path / "restart" / "stages"
    stages.mkdir(parents=True)
    bad = stages / "bad.json"
    bad.write_text('{"pid":')
    error = None
    entered = False
    with patch.object(cl, "remove_dead_stages"):
        try:
            with cl.stage_admit("Stage 2", "check", qdir=tmp_path / "buildq", holds=("team", ["wo"])):
                entered = True
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            error = exc
    assert error is None, f"admission raised {error!r}"
    assert entered
    assert bad.read_text() == '{"pid":'
