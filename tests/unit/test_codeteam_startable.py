import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_startable import startable  # noqa: E402


def no_hold(cls):
    return None


def not_warm(lock):
    return False


def port_of(job):
    return job.get("port")


def job(**extra):
    return {"class": "dev", "cost": 1, "worktree": "/wt/a", **extra}


def test_free_priced_job_starts():
    assert startable(job(port="rust"), set(), no_hold, not_warm, port_of) is True


def test_guard_hold_on_its_class_stops_it():
    hold = {"dev": "swap"}.get
    assert startable(job(), set(), hold, not_warm, port_of) is False
    assert startable(job(**{"class": "full"}), set(), hold, not_warm, port_of) is True


def test_unpriced_job_waits():
    assert startable(job(cost=None), set(), no_hold, not_warm, port_of) is False


def test_zero_cost_is_priced():
    assert startable(job(cost=0), set(), no_hold, not_warm, port_of) is True


def test_held_warm_lock_stops_it():
    assert startable(job(warm_lock="/wt/a/.warm"), set(), no_hold, lambda lock: lock == "/wt/a/.warm",
                     port_of) is False


def test_same_worktree_and_port_running_stops_it():
    assert startable(job(port="rust"), {("/wt/a", "rust")}, no_hold, not_warm, port_of) is False


def test_other_port_or_worktree_running_does_not_stop_it():
    busy = {("/wt/a", "swift"), ("/wt/b", "rust")}
    assert startable(job(port="rust"), busy, no_hold, not_warm, port_of) is True


def test_job_without_port_ignores_busy():
    assert startable(job(), {("/wt/a", None)}, no_hold, not_warm, port_of) is True
