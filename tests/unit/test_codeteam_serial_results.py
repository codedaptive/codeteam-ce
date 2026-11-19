import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_serial_results import serial_results


def test_each_step_finishes_before_the_next_starts_and_results_keep_order():
    events = []

    def procs():
        for name in ("one", "two"):
            events.append(f"start {name}")
            yield name

    def finish(name):
        events.append(f"finish {name}")
        return {"name": name}

    seen = []
    results = serial_results(procs(), finish, seen.append, lambda procs: events.append("stop"))
    assert results == [{"name": "one"}, {"name": "two"}]
    assert seen == [{"name": "one"}, {"name": "two"}]
    assert events == ["start one", "finish one", "start two", "finish two"]


def test_no_on_result_still_returns_every_result():
    assert serial_results(iter(["a", "b"]), lambda name: {"name": name}, None, lambda procs: None) == [
        {"name": "a"}, {"name": "b"}]


def test_an_interrupted_step_is_stopped_raised_and_no_later_step_starts():
    started, stopped = [], []

    def procs():
        for name in ("one", "two", "three"):
            started.append(name)
            yield name

    def finish(name):
        if name == "two":
            raise KeyboardInterrupt
        return {"name": name}

    with pytest.raises(KeyboardInterrupt):
        serial_results(procs(), finish, None, stopped.append)
    assert stopped == [["two"]]
    assert started == ["one", "two"]
