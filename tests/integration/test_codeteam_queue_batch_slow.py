import contextlib
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_queue_batch import queue_batch


class CheckoutFailed(Exception):
    def __init__(self, M, error):
        super().__init__(error)
        self.M = M
        self.error = error


def fake_batch_tree(base, entries, merge_one, conflict):
    kept = []
    for key, members in entries:
        previous = base
        for wo, tip in members:
            base, files = merge_one(base, wo, tip)
            if base is None:
                conflict(key, files, wo)
                base = previous
                break
        else:
            kept.append(key)
    return base, kept


@pytest.fixture
def fixture(tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    paths = [queue / "01.json", queue / "02.json"]
    entries = [
        {"wo": "a", "wos": ["a", "a2"], "tip": "ta", "tips": [["a", "ta"], ["a2", "ta2"]],
         "base": "base", "zones": ["A"], "files": ["src/a", "shared"], "integration": "owed", "review": "land"},
        {"wo": "b", "wos": ["b"], "tip": "tb", "base": "base", "zones": ["B"],
         "files": ["shared", "src/b"], "integration": "owed", "review": "land"},
    ]
    for path, entry in zip(paths, entries):
        path.write_text(json.dumps(entry))
    records = {wo: {"wo": wo, "zone": zone, "queued": "now", "stage2": []}
               for wo, zone in (("a", "A"), ("a2", "A"), ("b", "B"))}
    saves, landed, runs = [], [], []
    state = {"tip": "old", "checkout": None, "fail": None, "conflict": None, "moved": False,
             "compile_fail": False, "text": "src/b.py:7: AssertionError"}
    tree = tmp_path / "itest"
    (tree / "src").mkdir(parents=True)
    (tree / "src/b.py").write_text("line\n" * 7)
    team = SimpleNamespace(dir=tmp_path, repo=tmp_path / "repo", landing="landing", integration="integration",
                           manifest=tmp_path / "team.toml",
                           wo=lambda wo: records[wo], save_wo=lambda rec: saves.append(copy.deepcopy(rec)),
                           notify=Mock(), log=Mock())

    def out(repo, *args):
        assert repo == team.repo
        if args == ("rev-parse", "refs/heads/integration"):
            return "integ"
        if args[:2] == ("diff", "-U0"):
            return {"integ...ta": '--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n+x\n',
                    "integ...ta2": '--- a/a2.py\n+++ b/a2.py\n@@ -1 +1 @@\n+x\n',
                    "integ...tb": '--- a/src/b.py\n+++ b/src/b.py\n@@ -7 +7 @@\n+x\n',
                    "integ...tc": '--- a/src/c.py\n+++ b/src/c.py\n@@ -1 +1 @@\n+x\n'}[args[2]]
        assert args == ("rev-parse", "refs/heads/landing")
        if state["moved"] and state["checkout"] is not None:
            return "moved"
        return state["tip"]

    def checkout(team_, commit):
        assert team_ is team
        state["checkout"] = commit
        return tmp_path / "itest"

    def merge(team_, base, current, rec, tip):
        if rec["wo"] == state["conflict"]:
            return None, ["bad.py"]
        return current + "+" + tip, []

    def steps(team_, tree, zones, files):
        runs.append((state["checkout"], set(zones), set(files)))
        return [("compile A", "compile")], [("tests A", "test")]

    def results(tree, steps_, env, **kwargs):
        group = kwargs.get("group")
        return [{"name": name, "outcome": "FAIL" if (group == "compile" and state["compile_fail"]) or
                 (group == "integration" and state["fail"] and state["fail"] in state["checkout"].split("+"))
                 else "PASS", "seconds": 1,
                 "group": group, "text": state["text"]} for name, _ in steps_]

    def keep_logs(team_, commit, rows):
        for row in rows:
            row.pop("text", None)
            if row["outcome"] != "PASS":
                row.update(failing=["test_failure"], log="/logs/failure.log")

    def stage_record(rows, group=None):
        return [{"step": row["name"], "result": row["outcome"].lower(), "seconds": 1, "group": group}
                for row in rows]

    def land_entry(team_, path):
        entry = json.loads(path.read_text())
        landed.append((entry["wo"], copy.deepcopy(saves)))
        state["tip"] += "+" + "+".join(tip for _, tip in entry.get("tips", [[entry["wo"], entry["tip"]]]))
        path.unlink()
        return 0

    def send_back(wos, landing, commit, rows, frames):
        failures = [row for row in rows if row["outcome"] != "PASS"]
        return " ".join([*wos, landing, commit[:10], str(frames)] +
                        [f"{r['name']} {r['failing'][0]} {r['log']}" for r in failures])

    def recheck_at(lock, checkout_, run, failure, failed):
        with lock:
            try:
                tree = checkout_()
            except failure as exc:
                return failed(exc)
            return run(tree)

    land = SimpleNamespace(
        Lock=lambda *args: contextlib.nullcontext(), itest_lock=lambda *args: contextlib.nullcontext(),
        itest_checkout=Mock(side_effect=checkout), CheckoutFailed=CheckoutFailed, recheck_at=recheck_at,
        recheck_steps=Mock(side_effect=steps), step_results=Mock(side_effect=results),
        keep_recheck_logs=Mock(side_effect=keep_logs), team_env=Mock(return_value={}),
        stage2_record=Mock(side_effect=stage_record), slow_tests_flag=Mock(return_value={"total_s": 901}),
        report_slow_tests=Mock(), test_run_s=Mock(return_value=1000.0),
        is_test_step=Mock(), step_run_seconds=Mock(),
        merge_landing_member=Mock(side_effect=merge), landing_conflict=Mock(),
        conflicting_landings=Mock(return_value=["prior"]), land_entry=Mock(side_effect=land_entry),
        out=Mock(side_effect=out), now=Mock(return_value="finished"),
        zone_session=lambda team_, zone: "Coord-" + zone,
        stage_admit=lambda *args, **kwargs: contextlib.nullcontext(),
        CONFLICT=2, REFUSED=5,
        keep_stage2_records=Mock(side_effect=lambda folder, key, rows: [dict(row, kept=key) for row in rows]),
        failing_test_names=Mock(return_value=["test_failure"]),
        batch_tree=fake_batch_tree, integration_send_back=Mock(side_effect=send_back),
        entry_members=lambda e: [(w, t) for w, t in e["tips"]] if "tips" in e else [(e["wo"], e["tip"])])
    return SimpleNamespace(team=team, land=land, paths=paths, records=records, saves=saves,
                           landed=landed, runs=runs, state=state)


def _check_slow_report_source(f, first_zones, second_zones):
    for path, zones in zip(f.paths, (first_zones, second_zones)):
        entry = json.loads(path.read_text())
        entry["zones"] = zones
        path.write_text(json.dumps(entry))
    f.land.slow_tests_flag.return_value = {"total_s": 1200, "limit_s": 900, "steps": [
        {"step": "tests B (src/b)", "run_s": 800, "queued_s": 0},
        {"step": "tests A (src/a)", "run_s": 400, "queued_s": 0},
    ]}

    def owner(team, name):
        assert team is f.team
        return {"tests B (src/b)": "B", "tests A (src/a)": "A"}[name]

    f.land.step_owner = Mock(side_effect=owner)
    assert queue_batch(f.team, f.paths, f.land) is True
    f.land.report_slow_tests.assert_called_once()
    args = f.land.report_slow_tests.call_args.args
    assert args[2] == "a, a2, b"
    assert set(args[5]) == {"src/a", "src/b", "shared"}
    assert args[4] == {"wo": "b", "zone": "B", "stage": 2, "commit": "integ+ta+ta2+tb"}
    f.land.step_owner.assert_called_once_with(f.team, "tests B (src/b)")


def test_slow_report_selects_matching_entry_over_wider_nonmatching_first(fixture):
    _check_slow_report_source(fixture, ["A", "C", "D", "E", "F"], ["B"])


def test_slow_report_selects_widest_matching_entry_even_when_later(fixture):
    _check_slow_report_source(fixture, ["A", "B"], ["B", "C", "D"])


def test_slow_report_excludes_conflicted_entry(fixture):
    f = fixture
    f.state["conflict"] = "b"
    f.land.slow_tests_flag.return_value = {"total_s": 1200, "limit_s": 900, "steps": [
        {"step": "tests B (src/b)", "run_s": 800, "queued_s": 0},
        {"step": "tests A (src/a)", "run_s": 400, "queued_s": 0},
    ]}
    f.land.step_owner = Mock(side_effect=lambda team, name: {"tests B (src/b)": "B", "tests A (src/a)": "A"}[name])
    assert queue_batch(f.team, f.paths, f.land) is True
    assert [name for name, _ in f.landed] == ["a"]
    f.land.report_slow_tests.assert_called_once()
    args = f.land.report_slow_tests.call_args.args
    assert args[4] == {"wo": "a", "zone": "A", "stage": 2, "commit": "integ+ta+ta2"}
    assert args[2] == "a, a2"
    assert set(args[5]) == {"src/a", "shared"}
