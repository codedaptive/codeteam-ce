import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_team_counts import team_counts  # noqa: E402


def test_counts_running_and_all_waiting_by_team_including_fallback_and_no_team():
    jobs = [
        {"team": "team-acme", "state": "running"},
        {"team": "team-acme", "state": "queued", "hold": "warm"},
        {"team": "", "worktree": "/x/team-acme/wo", "state": "queued"},
        {"worktree": "/x/team-widgets/wo", "state": "running"},
        {"state": "queued"},
        {"worktree": "/x/no-team/wo", "state": "running"},
    ]
    assert team_counts(jobs) == {
        "acme": {"running": 1, "waiting": 2},
        "widgets": {"running": 1, "waiting": 0},
        "-": {"running": 1, "waiting": 1},
    }


def test_done_and_broken_jobs_do_not_count_or_create_teams():
    assert team_counts([{"team": "team-a", "state": "done"},
                        {"team": "team-b", "state": "broken"}]) == {}
