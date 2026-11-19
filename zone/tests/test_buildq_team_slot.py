import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def buildq(monkeypatch):
    name = "codeteam_buildq"
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / "bin" / "codeteam-buildq"))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    loader.exec_module(module)
    return module


@pytest.fixture
def setup_runner(buildq, tmp_path, monkeypatch):
    q = tmp_path / "queue"
    q.mkdir()
    runner = buildq.Runner(q, tmp_path / "queue.toml")
    starts = []
    monkeypatch.setattr(buildq, "warm_held", lambda path: path == "held")

    def spawn(self, job):
        starts.append(json.loads((q / (job["ticket"] + ".json")).read_text()))
        return SimpleNamespace(pid=12345)

    monkeypatch.setattr(buildq.Runner, "spawn", spawn)
    cfg = buildq.Config(budget=8, shares=buildq.SHARES, swap_max=0.9, retention_hours=24, slot_cost=1)
    guard = buildq.Guard(swap=0.0, swap_max=0.9)

    def setup(jobs):
        for j in jobs:
            (q / (j["ticket"] + ".json")).write_text(json.dumps(j))
        runner.jobs = {j["ticket"]: j for j in jobs}
        return runner, cfg, guard, starts

    return setup


def job(ticket, team="team-acme", state="queued", submitted=1, **fields):
    return {"ticket": ticket, "team": team, "state": state, "kind": "run", "class": "dev",
            "key": "k-" + ticket, "command": [], "submitted": submitted, "cost": 1,
            "tool": "unused", "record": None, "env": {}, **fields}


def full_acme():
    return [job("m" + str(i), state="running") for i in range(8)]


def test_idle_team_starts_over_budget_and_marks_file_before_spawn(setup_runner):
    runner, cfg, guard, starts = setup_runner(full_acme() + [job("mq"), job("t", "team-widgets")])
    runner.start_jobs(cfg, guard)
    assert runner.jobs["t"]["state"] == "running"
    assert runner.jobs["mq"]["state"] == "queued"
    assert sum(j["cost"] for j in runner.jobs.values() if j["state"] == "running") == 9
    assert starts[0]["guarantee"] == "team"
    assert starts[0]["state"] == "running"
    assert json.loads((runner.q / "t.json").read_text())["guarantee"] == "team"


def test_guarantee_is_in_first_running_job_file_write(setup_runner):
    runner, cfg, guard, starts = setup_runner([job("t", "team-widgets")])
    runner.start_jobs(cfg, guard)
    assert starts[0].get("guarantee") == "team"
    assert starts[0]["state"] == "running"
    assert json.loads((runner.q / "t.json").read_text()).get("guarantee") == "team"


def test_running_team_gets_no_second_guaranteed_start(setup_runner):
    running = full_acme()[:7] + [job("tr", "team-widgets", state="running")]
    runner, cfg, guard, _ = setup_runner(running + [job("tq", "team-widgets")])
    runner.start_jobs(cfg, guard)
    assert runner.jobs["tq"]["state"] == "queued"


def test_idle_team_reserves_nothing_from_shared_pool(setup_runner):
    runner, cfg, guard, _ = setup_runner([job("m" + str(i), submitted=i) for i in range(10)])
    runner.start_jobs(cfg, guard)
    assert sum(j["state"] == "running" for j in runner.jobs.values()) == 8


@pytest.mark.parametrize("fields", [{"warm_lock": "held"}, {"cost": None}])
def test_warm_held_or_unpriced_team_job_does_not_start(setup_runner, fields):
    runner, cfg, guard, _ = setup_runner([job("t", "team-widgets", **fields)])
    runner.start_jobs(cfg, guard)
    assert runner.jobs["t"]["state"] == "queued"


def test_port_busy_team_job_does_not_start(setup_runner):
    same = {"worktree": "/tmp/test-worktree", "key": "one pkg/rust/x"}
    runner, cfg, guard, _ = setup_runner([job("m", state="running", **same), job("t", "team-widgets", **same)])
    runner.start_jobs(cfg, guard)
    assert runner.jobs["t"]["state"] == "queued"


def test_swap_held_team_job_does_not_start(setup_runner, buildq):
    runner, cfg, _, _ = setup_runner([job("t", "team-widgets")])
    runner.start_jobs(cfg, buildq.Guard(swap=0.95, swap_max=0.9))
    assert runner.jobs["t"]["state"] == "queued"


def test_worktree_fallback_gets_team_start_over_budget(setup_runner):
    waiting = job("t", team=None, worktree="/tmp/x/team-widgets/wo/a")
    del waiting["team"]
    runner, cfg, guard, _ = setup_runner(full_acme() + [waiting])
    runner.start_jobs(cfg, guard)
    assert runner.jobs["t"]["state"] == "running"
    assert json.loads((runner.q / "t.json").read_text())["guarantee"] == "team"


def test_worktree_fallback_with_running_team_gets_no_guarantee(setup_runner):
    running = job("tr", team=None, state="running", worktree="/tmp/x/team-widgets/wo/a")
    waiting = job("tq", team=None, worktree="/tmp/x/team-widgets/wo/b")
    del running["team"], waiting["team"]
    runner, cfg, guard, _ = setup_runner(full_acme()[:7] + [running, waiting])
    runner.start_jobs(cfg, guard)
    assert runner.jobs["tq"]["state"] == "queued"


def test_two_teams_start_in_choice_submission_order(setup_runner):
    runner, cfg, guard, starts = setup_runner(full_acme() + [job("late", "team-b", submitted=9),
                                                           job("early", "team-a", submitted=2)])
    runner.start_jobs(cfg, guard)
    assert [j["ticket"] for j in starts] == ["early", "late"]
    assert [j.get("guarantee") for j in starts] == ["team", "team"]


def test_team_guarantee_precedes_class_guarantee(setup_runner):
    runner, cfg, guard, starts = setup_runner(full_acme() + [job("land", None, **{"class": "land"}),
                                                           job("team", "team-a", submitted=9)])
    runner.start_jobs(cfg, guard)
    assert [j["ticket"] for j in starts] == ["team", "land"]
    assert starts[0].get("guarantee") == "team"
    assert "guarantee" not in starts[1]


def test_team_guarantee_ignores_class_ceiling(setup_runner):
    jobs = [job("p1", "team-acme", "running", **{"class": "post"}),
            job("p2", "team-acme", "running", **{"class": "post"}),
            job("t", "team-widgets", **{"class": "post"})]
    runner, cfg, guard, _ = setup_runner(jobs)
    runner.start_jobs(cfg, guard)
    assert runner.jobs["t"]["state"] == "running"
    assert runner.jobs["t"].get("guarantee") == "team"


def test_class_loop_start_has_no_guarantee_key(setup_runner):
    runner, cfg, guard, _ = setup_runner([job("m", state="running"), job("next")])
    runner.start_jobs(cfg, guard)
    assert runner.jobs["next"]["state"] == "running"
    assert "guarantee" not in json.loads((runner.q / "next.json").read_text())


def test_heartbeat_contains_literal_team_counts_and_existing_fields(setup_runner):
    jobs = [job("m", state="running"), job("mw", warm_lock="held"),
            job("t", None, worktree="/tmp/x/team-widgets/wo"),
            job("unknown", None, worktree="/tmp/x/other"), job("done", "team-old", "done")]
    runner, cfg, guard, _ = setup_runner(jobs)
    runner.write_heartbeat(cfg, guard, list(runner.jobs.values()))
    beat = json.loads((runner.q.parent / "queue-runner.json").read_text())
    assert beat.get("teams") == {"acme": {"running": 1, "waiting": 1},
                             "widgets": {"running": 0, "waiting": 1},
                             "-": {"running": 0, "waiting": 1}}
    assert beat["pid"] == os.getpid()
    assert isinstance(beat["beat"], (int, float))
    assert {k: beat[k] for k in ("budget", "used", "swap", "swap_max", "swap_hold")} == {
        "budget": 8, "used": 1, "swap": 0.0, "swap_max": 0.9, "swap_hold": False}
