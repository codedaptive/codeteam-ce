import importlib.machinery
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SINGLE_WAIT = "zone-test: a run is already going in this worktree; waiting for its result"


@pytest.fixture
def zone_tool():
    loader = importlib.machinery.SourceFileLoader("zone_tool_single_wait", str(ROOT / "bin" / "zone-tool"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_wait_for_lock_repeats_at_each_interval_until_taken(zone_tool):
    now = 0
    tries = 0
    sleeps = []
    said = []

    def try_lock():
        nonlocal tries
        tries += 1
        if tries > 1000:
            raise AssertionError("wait_for_lock did not stop after taking the lock")
        return tries == 1000

    def sleep(seconds):
        nonlocal now
        sleeps.append(seconds)
        now += seconds

    result = zone_tool.wait_for_lock(try_lock, lambda: now, sleep,
                                     lambda line: said.append((now, line)), 150, 1)

    assert result is None
    assert tries == 1000
    assert sleeps == [1] * 999
    assert said == [(0, SINGLE_WAIT), (150, SINGLE_WAIT), (300, SINGLE_WAIT),
                    (450, SINGLE_WAIT), (600, SINGLE_WAIT), (750, SINGLE_WAIT),
                    (900, SINGLE_WAIT)]


def test_wait_for_lock_immediate_acquisition_is_silent(zone_tool):
    sleeps = []
    said = []

    result = zone_tool.wait_for_lock(lambda: True, lambda: 0, sleeps.append, said.append, 150, 1)

    assert result is None
    assert said == []
    assert sleeps == []
