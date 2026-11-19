import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_settled_env import settled_env  # noqa: E402


@pytest.mark.parametrize("state", ["done", "broken"])
def test_settled_job_gets_empty_env_without_mutating_input(state):
    job = {"state": state, "ticket": "T1", "env": {"JOBENV_FAKE": "x"}, "result": "example"}
    result = settled_env(job)
    assert result == {"state": state, "ticket": "T1", "env": {}, "result": "example"}
    assert result is not job
    assert job == {"state": state, "ticket": "T1", "env": {"JOBENV_FAKE": "x"}, "result": "example"}


@pytest.mark.parametrize("state", ["queued", "running"])
def test_unsettled_job_keeps_its_env(state):
    job = {"state": state, "env": {"JOBENV_FAKE": "x"}, "ticket": "T1"}
    assert settled_env(job) == {"state": state, "env": {"JOBENV_FAKE": "x"}, "ticket": "T1"}


@pytest.mark.parametrize("state", ["done", "broken"])
def test_settled_job_without_env_does_not_gain_one(state):
    assert settled_env({"state": state, "ticket": "T1"}) == {"state": state, "ticket": "T1"}


def test_settled_job_with_empty_env_still_returns_a_copy():
    job = {"state": "done", "env": {}}
    result = settled_env(job)
    assert result == {"state": "done", "env": {}}
    assert result is not job
