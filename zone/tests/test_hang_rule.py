import importlib.machinery
import importlib.util
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load_file(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def hang():
    return load_file("hang_rule_under_test", ROOT / "share" / "codeteam_hang.py")


@pytest.fixture
def zone_tool():
    return load_file("zone_tool_hang_under_test", ROOT / "bin" / "zone-tool")


def test_settings_defaults(hang):
    assert hang.settings({}) == (600.0, 1.0)


def test_settings_reads_both_environment_values(hang):
    assert hang.settings({"CODETEAM_HANG_WINDOW": "25.5", "CODETEAM_HANG_CPU_PCT": "3.5"}) == (25.5, 3.5)


@pytest.mark.parametrize("bad", ["not-a-number", "nan", "inf", "-inf", "0", "-2"])
@pytest.mark.parametrize("field", ["window", "cpu"])
def test_settings_invalid_value_only_resets_that_setting(hang, bad, field):
    env = {"CODETEAM_HANG_WINDOW": "30", "CODETEAM_HANG_CPU_PCT": "4"}
    if field == "window":
        env["CODETEAM_HANG_WINDOW"] = bad
        assert hang.settings(env) == (600.0, 4.0)
    else:
        env["CODETEAM_HANG_CPU_PCT"] = bad
        assert hang.settings(env) == (30.0, 1.0)


@pytest.mark.parametrize("text, seconds", [
    ("0:00.09", 0.09),
    ("1:02.50", 62.5),
    ("1:00:00.00", 3600.0),
    ("2-01:00:00", 176400.0),
])
def test_parse_cputime(hang, text, seconds):
    assert hang.parse_cputime(text) == seconds


@pytest.fixture
def process_table(hang, monkeypatch):
    table = {10: (1, 0.0), 11: (10, 0.0), 12: (11, 0.0),
             13: (10, 0.0), 14: (13, 0.0), 20: (1, 0.0)}
    monkeypatch.setattr(hang, "_rusage_cpu", lambda pid: table[pid][1], raising=False)
    return table


def test_tree_cpu_includes_root_and_descendants_only(hang, process_table):
    assert set(hang.tree_cpu(10, table=process_table)) == {10, 11, 12, 13, 14}


def test_tree_cpu_excludes_a_subtree(hang, process_table):
    assert set(hang.tree_cpu(10, table=process_table, exclude=(11,))) == {10, 13, 14}


def test_tree_cpu_missing_root_is_unknown(hang, process_table):
    assert hang.tree_cpu(99, table=process_table) is None


def test_idle_tree_is_hung_after_full_window(hang):
    watch = hang.HangWatch(100, 1, 0)
    watch.sample(0, {10: 0.0})
    watch.sample(100, {10: 0.0})
    reason = watch.hung(100)
    assert isinstance(reason, str) and reason.startswith("hung:")


def test_idle_tree_is_not_hung_before_full_window(hang):
    watch = hang.HangWatch(100, 1, 10)
    watch.sample(109, {10: 0.0})
    assert watch.hung(109) is None


def test_recent_output_prevents_hang(hang):
    watch = hang.HangWatch(100, 1, 0)
    watch.sample(100, {10: 0.0})
    watch.output(50)
    assert watch.hung(100) is None


def test_short_lived_busy_workers_prevent_hang(hang):
    watch = hang.HangWatch(100, 1, 0)
    for t in range(1, 101):
        watch.sample(t, {1000 + t: 0.05})
    assert watch.hung(100) is None


@pytest.mark.parametrize("cpu, pct, is_hung", [
    (0.9, 1, True),
    (1.5, 1, False),
    (1.5, 5, True),
    (5.0, 5, False),
])
def test_cpu_threshold_is_strict_and_uses_percentage(hang, cpu, pct, is_hung):
    watch = hang.HangWatch(100, pct, 0)
    watch.sample(100, {10: cpu})
    reason = watch.hung(100)
    if is_hung:
        assert isinstance(reason, str) and reason.startswith("hung:")
    else:
        assert reason is None


def test_unknown_sample_prevents_hang(hang):
    watch = hang.HangWatch(100, 1, 0)
    watch.sample(50, None)
    watch.sample(100, {10: 0.0})
    assert watch.hung(100) is None


def test_no_sample_in_trailing_window_prevents_hang(hang):
    watch = hang.HangWatch(100, 1, 0)
    watch.sample(1, {10: 0.0})
    assert watch.hung(250) is None


def test_expired_unknown_sample_no_longer_prevents_hang(hang):
    watch = hang.HangWatch(100, 1, 0)
    watch.sample(1, None)
    watch.sample(101, {10: 0.0})
    reason = watch.hung(101)
    assert isinstance(reason, str) and reason.startswith("hung:")


def test_output_can_be_ignored(hang):
    watch = hang.HangWatch(100, 1, 0, watch_output=False)
    watch.sample(100, {10: 0.0})
    watch.output(99)
    reason = watch.hung(100)
    assert isinstance(reason, str) and reason.startswith("hung:")


class FakeProcess:
    def __init__(self, timeouts):
        self.timeouts = timeouts
        self.calls = 0

    def wait(self, timeout):
        self.calls += 1
        if self.calls > 20:
            raise AssertionError("hang_wait failed to stop")
        if self.calls <= self.timeouts:
            raise subprocess.TimeoutExpired("fake", timeout)
        return 0


def test_hang_wait_returns_exit_code_after_timeouts(hang, zone_tool):
    proc = FakeProcess(2)
    clock = iter([1, 2])
    result = zone_tool.hang_wait(proc, hang.HangWatch(100, 1, 0),
                                 lambda: next(clock), lambda: {10: 0.0}, 1)
    assert result == (0, None)
    assert proc.calls == 3


def test_hang_wait_stops_on_hang(hang, zone_tool):
    proc = FakeProcess(20)
    clock = iter([1, 2, 3, 4, 5])
    rc, reason = zone_tool.hang_wait(proc, hang.HangWatch(3, 1, 0),
                                     lambda: next(clock), lambda: {10: 0.0}, 1)
    assert rc is None
    assert isinstance(reason, str) and reason.startswith("hung:")
    assert proc.calls == 3
