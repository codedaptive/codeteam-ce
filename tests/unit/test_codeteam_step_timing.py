import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))

SUMMARY = "zone-test: PASS (exit 0); record /tmp/r.json"


@pytest.mark.parametrize(("text", "expected"), [
    ("zone-tool: queued 360 s, ran 449 s (job a, build 160 s)\n" + SUMMARY + "\n",
     {"ran": 449, "build": 160}),
    ("zone-tool: queued 3 s, ran 7 s (job a)\n" + SUMMARY, {"ran": 7}),
    ("zone-test: PASS (exit 0); answered from record /tmp/r.json\n", {"ran": 0}),
    ("all passed\n", {}),
])
def test_step_timing_contains_only_observed_values(text, expected):
    from codeteam_step_timing import step_timing

    assert step_timing(text) == expected
