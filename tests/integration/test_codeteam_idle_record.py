import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_idle_record import idle_record


def test_open_record_is_read(tmp_path):
    (tmp_path / "a.json").write_text('{"wo": "a", "tree": "/t/a"}')
    assert idle_record(tmp_path / "a.json") == {"wo": "a", "tree": "/t/a"}


def test_landed_record_is_read(tmp_path):
    (tmp_path / "a.landed.json").write_text('{"wo": "a", "tree": "/t/a"}')
    assert idle_record(tmp_path / "a.landed.json") == {"wo": "a", "tree": "/t/a"}


def test_retired_record_is_not_read(tmp_path):
    (tmp_path / "a.retired.json").write_text('{"wo": "a", "tree": "/t/a"}')
    with patch.object(Path, "read_text", side_effect=AssertionError("read")):
        assert idle_record(tmp_path / "a.retired.json") is None


def test_record_gone_since_the_listing_is_none(tmp_path):
    assert idle_record(tmp_path / "gone.json") is None


def test_half_written_record_is_none(tmp_path):
    (tmp_path / "c.json").write_text('{"wo": "c", "zo')
    assert idle_record(tmp_path / "c.json") is None
