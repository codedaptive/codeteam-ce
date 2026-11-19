import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))

from codeteam_ran import ran_seconds


SUMMARY = "zone-test: PASS (exit 0); record /t/.test-record.json\n"
ONE = f"zone-tool: queued 360 s, ran 449 s (job a, build 160 s)\n{SUMMARY}"
TWO = f"zone-tool: queued 7 s, ran 50 s (job b, build 40 s)\n{SUMMARY}"
OLD = f"zone-tool: queued 10 s, ran 9 s (job old)\n{SUMMARY}"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(ONE, 160, id="one-job"),
        pytest.param(ONE + TWO, 200, id="two-jobs"),
        pytest.param(f"zone-tool: queued 0 s, ran 9 s (job c, build 5 s)\n{SUMMARY}" + OLD,
                     5, id="new-and-old"),
        pytest.param(OLD, None, id="old-only"),
        pytest.param("", None, id="empty"),
        pytest.param("zone-tool: queued 0 s, ran 9 s (job c, build 5 s)\nother output\n", None,
                     id="no-immediate-summary"),
        pytest.param("prefix zone-tool: queued 0 s, ran 9 s (job c, build 5 s)\n" + SUMMARY,
                     None, id="job-not-at-line-start"),
        pytest.param(f"zone-tool: queued 0 s, ran 9 s (job c, build 0 s)\n{SUMMARY}",
                     0, id="zero-build"),
    ],
)
def test_build_seconds_sums_only_jobs_followed_by_summary(text, expected):
    from codeteam_build_seconds import build_seconds

    assert build_seconds(text) == expected


def test_ran_seconds_reads_job_with_build_part():
    text = f"zone-tool: queued 360 s, ran 449 s (job a, build 175 s)\n{SUMMARY}"
    assert ran_seconds(text) == 449
