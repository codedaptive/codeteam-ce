import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_clean_settled_env import clean_settled_env  # noqa: E402


class FakeQueue:
    def __init__(self, jobs, rejected=()):
        self.jobs = jobs
        self.rejected = rejected
        self.calls = []

    def all(self):
        return self.jobs

    def update(self, ticket, change, expect=None):
        self.calls.append((ticket, change, expect))
        return None if ticket in self.rejected else {"ticket": ticket, **change}


def test_only_nonempty_settled_envs_are_updated_with_expected_state():
    queue = FakeQueue([
        {"ticket": "D", "state": "done", "env": {"JOBENV_FAKE": "x"}},
        {"ticket": "B", "state": "broken", "env": {"JOBENV_FAKE": "x"}},
        {"ticket": "Q", "state": "queued", "env": {"JOBENV_FAKE": "x"}},
        {"ticket": "R", "state": "running", "env": {"JOBENV_FAKE": "x"}},
        {"ticket": "E", "state": "done", "env": {}},
        {"ticket": "N", "state": "broken"},
    ])
    assert clean_settled_env(queue) == 2
    assert queue.calls == [("D", {"env": {}}, "done"), ("B", {"env": {}}, "broken")]


def test_count_excludes_updates_rejected_after_state_changes():
    queue = FakeQueue([
        {"ticket": "D", "state": "done", "env": {"JOBENV_FAKE": "x"}},
        {"ticket": "B", "state": "broken", "env": {"JOBENV_FAKE": "x"}},
    ], rejected=("D",))
    assert clean_settled_env(queue) == 1
    assert queue.calls == [("D", {"env": {}}, "done"), ("B", {"env": {}}, "broken")]


def test_empty_queue_requires_no_updates():
    queue = FakeQueue([])
    assert clean_settled_env(queue) == 0
    assert queue.calls == []
