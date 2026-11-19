import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_team_slot import team_slot  # noqa: E402


CLASSES = ("land", "full", "post", "pre", "dev")


def job(team, cls="dev", submitted=1, state="queued", **extra):
    return {"team": team, "class": cls, "submitted": submitted, "state": state, **extra}


def test_running_slot_in_any_class_disqualifies_team():
    waiting = job("team-a")
    jobs = [waiting, job("team-a", "full", state="running", kind="slot")]
    assert team_slot(jobs, CLASSES, lambda j: True) is None


def test_class_order_beats_age_within_a_team():
    old = job("team-a", "dev", 1)
    newer = job("team-a", "post", 10)
    assert team_slot([old, newer], CLASSES, lambda j: True) == newer


def test_oldest_startable_job_in_first_class_is_chosen():
    jobs = [job("team-a", "dev", 9), job("team-a", "dev", 3), job("team-a", "dev", 1, held=True)]
    assert team_slot(jobs, CLASSES, lambda j: not j.get("held")) == jobs[1]


def test_earliest_team_choice_wins_not_earliest_queued_job():
    jobs = [job("team-a", "dev", 1), job("team-a", "post", 9), job("team-b", "dev", 5)]
    assert team_slot(jobs, CLASSES, lambda j: True) == jobs[2]


def test_team_with_only_unstartable_job_does_not_qualify():
    jobs = [job("team-a", submitted=1, held=True), job("team-b", submitted=2)]
    assert team_slot(jobs, CLASSES, lambda j: not j.get("held")) == jobs[1]


def test_no_team_never_qualifies():
    assert team_slot([job(None)], CLASSES, lambda j: True) is None


def test_worktree_team_qualifies_without_team_field():
    waiting = {"worktree": "/x/team-a/wo", "class": "dev", "submitted": 1, "state": "queued"}
    assert team_slot([waiting], CLASSES, lambda j: True) == waiting


def test_done_and_broken_jobs_do_not_block_or_qualify():
    waiting = job("team-a", submitted=5)
    jobs = [job("team-a", state="done"), job("team-a", state="broken"),
            job("team-b", state="done"), waiting]
    assert team_slot(jobs, CLASSES, lambda j: True) == waiting
    assert team_slot(jobs[:-1], CLASSES, lambda j: True) is None


def test_class_not_in_classes_does_not_qualify():
    assert team_slot([job("team-a", "other")], CLASSES, lambda j: True) is None
