import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_job_team import job_team  # noqa: E402


def test_explicit_nonempty_team_takes_precedence():
    assert job_team({"team": "team-acme", "worktree": "/x/team-widgets/a"}) == "team-acme"


def test_empty_or_nonstring_team_falls_back_to_first_worktree_team():
    for team in ("", None, 42):
        assert job_team({"team": team, "worktree": "/x/team-widgets/team-acme/a"}) == "team-widgets"


def test_missing_team_falls_back_to_worktree():
    assert job_team({"worktree": "/x/team-acme/wo"}) == "team-acme"


def test_no_team_or_matching_worktree_returns_none():
    assert job_team({}) is None
    assert job_team({"worktree": "/x/not-team-acme/wo"}) is None
