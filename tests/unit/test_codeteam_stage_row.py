import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))


def test_valid_stage_record_is_returned():
    from codeteam_stage_row import stage_row

    assert stage_row('{"pid": 12, "stage": "Stage 2"}') == {"pid": 12, "stage": "Stage 2"}


@pytest.mark.parametrize("text", ['{"pid":', '[]', '{}', '{"pid": "12"}', '{"pid": true}'])
def test_invalid_stage_record_is_skipped(text):
    from codeteam_stage_row import stage_row

    assert stage_row(text) is None
