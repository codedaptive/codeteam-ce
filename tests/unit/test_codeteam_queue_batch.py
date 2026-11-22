import contextlib
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
import codeteam_queue_batch
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


def test_whole_batch_passes_and_saves_rows_before_landing_in_order(fixture):
    f = fixture
    assert queue_batch(f.team, f.paths, f.land) is True
    assert [name for name, _ in f.landed] == ["a", "b"]
    assert f.runs == [("integ+ta+ta2+tb", {"A", "B"}, {"src/a", "src/b", "shared"})]
    saved_before_first_land = {row["wo"]: row for row in f.landed[0][1]}
    for wo in ("a", "a2", "b"):
        assert saved_before_first_land[wo]["stage2"] == [
            {"step": "compile A", "result": "pass", "seconds": 1, "group": "compile", "kept": "batch-integ+ta+t"},
            {"step": "tests A", "result": "pass", "seconds": 1, "group": "integration", "kept": "batch-integ+ta+t"}]
    f.land.keep_recheck_logs.assert_called_once()


def test_batch_measure_saved_for_every_member_before_first_land(fixture):
    f = fixture
    f.records["a"]["stage2_tests_s"] = 1200.0
    f.records["a2"]["stage2_tests_s"] = 400.0
    assert queue_batch(f.team, f.paths, f.land) is True
    saved = {row["wo"]: row for row in f.landed[0][1]}
    assert {wo: saved[wo].get("stage2_tests_s") for wo in ("a", "a2", "b")} == {
        "a": 1200.0, "a2": 1000.0, "b": 1000.0}


def test_failing_batch_runs_once_and_sends_back_only_the_matching_entry(fixture):
    f = fixture
    path_c = f.paths[0].parent / "03.json"
    path_c.write_text(json.dumps({"wo": "c", "tip": "tc", "base": "base", "zones": ["C"],
                                  "files": ["src/c.py"], "review": "land", "integration": "owed"}))
    f.paths.append(path_c)
    f.records["c"] = {"wo": "c", "zone": "C", "queued": "now", "stage2": []}
    f.state["fail"] = "tb"
    original_results = f.land.step_results.side_effect
    def results(*args, **kwargs):
        rows = original_results(*args, **kwargs)
        for row in rows:
            if row["outcome"] == "FAIL":
                row["text"] = "src/b.py:7: AssertionError"
        return rows
    f.land.step_results.side_effect = results
    original_out = f.land.out.side_effect
    def out(repo, *args):
        if args[:2] == ("diff", "-U0"):
            return {'integ...ta': '--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n+x\n',
                    'integ...ta2': '--- a/a2.py\n+++ b/a2.py\n@@ -1 +1 @@\n+x\n',
                    'integ...tb': '--- a/src/b.py\n+++ b/src/b.py\n@@ -7 +7 @@\n+x\n',
                    'integ...tc': '--- a/src/c.py\n+++ b/src/c.py\n@@ -1 +1 @@\n+x\n'}[args[2]]
        return original_out(repo, *args)
    f.land.out.side_effect = out
    f.land.failing_test_names = Mock(return_value=["test_failure"])
    f.land.keep_stage2_records = Mock(side_effect=lambda folder, key, rows: [dict(row, kept=key) for row in rows])
    f.land.integration_send_back.side_effect = lambda wos, integration, commit, rows, frames=None: str(frames)
    assert queue_batch(f.team, f.paths, f.land) is True
    assert len(f.runs) == 1
    assert [name for name, _ in f.landed] == ["a", "c"]
    assert "queued" not in f.records["b"]
    assert f.records["b"]["stage2"][-1]["kept"] == "batch-integ+ta+t"
    assert "src/b.py" in f.team.notify.call_args.args[2]


def test_unmatched_batch_failure_lands_every_entry_and_opens_finding(fixture):
    f = fixture
    f.state["fail"] = "tb"
    original_out = f.land.out.side_effect
    f.land.out.side_effect = lambda repo, *args: ('' if args[:2] == ("diff", "-U0")
                                                 else original_out(repo, *args))
    f.land.failing_test_names = Mock(return_value=["test_failure"])
    f.land.keep_stage2_records = Mock(side_effect=lambda folder, key, rows: [dict(row, kept=key) for row in rows])
    f.land.FindingsLock = lambda team: contextlib.nullcontext()
    f.land.all_findings = Mock(return_value=[])
    f.land.landed_rec = lambda team, wo: f.records[wo]
    f.land.feature_of = lambda rec: "feature"
    findings = []
    f.land.load_findings = lambda team, feature: findings
    f.land.save_findings = Mock()
    f.land.is_test_step = lambda name: name.startswith("tests ")
    f.land.step_owner = lambda team, name: "A"
    f.land.integration_send_back.side_effect = lambda wos, integration, commit, rows, frames=None: str(frames)
    assert queue_batch(f.team, f.paths, f.land) is True
    assert len(f.runs) == 1
    assert [name for name, _ in f.landed] == ["a", "b"]
    assert len(findings) == 1
    assert findings[0]["test"] == "tests A"
    assert findings[0]["wos"] == ["a", "a2", "b"]
    assert "FIX-FORWARD" in f.team.notify.call_args.args[2]


def test_matched_entry_is_sent_back_with_batch_results_and_other_entry_lands(fixture):
    f = fixture
    f.state["fail"] = "tb"
    assert queue_batch(f.team, f.paths, f.land) is True
    assert [name for name, _ in f.landed] == ["a"]
    assert not f.paths[1].exists()
    assert "queued" not in f.records["b"]
    assert f.records["b"]["stage2"][-1]["result"] == "fail"
    f.team.notify.assert_called_once()
    recipient, kind, text = f.team.notify.call_args.args
    assert (recipient, kind) == ("Coord-B", "REQUEST")
    assert all(s in text for s in ("b", "tests A", "test_failure", "/logs/failure.log"))
    assert f.team.log.call_args.args[0]["result"] == "integration failed"
    assert [commit for commit, _, _ in f.runs] == ["integ+ta+ta2+tb"]
    assert f.records["b"]["stage2"][-1]["kept"] == "batch-integ+ta+t"
    assert "src/b.py" in text


def test_failing_step_records_incomplete_callees(fixture, monkeypatch):
    f = fixture
    f.state["fail"] = "tb"
    monkeypatch.setattr(codeteam_queue_batch, "failing_test_callees",
                        Mock(return_value=[[["src/b.py", None]], ["test_failure"]]))
    verdict = Mock(return_value=True)
    monkeypatch.setattr(codeteam_queue_batch, "batch_verdict", verdict)
    assert queue_batch(f.team, f.paths, f.land) is True
    result = verdict.call_args.args[3]["results"][1]
    assert result["callees_incomplete"] == ["test_failure"]
    assert result["frames"] == [["src/b.py", 7], ["src/b.py", None]]


def test_failing_step_omits_incomplete_key_when_callees_complete(fixture, monkeypatch):
    f = fixture
    f.state["fail"] = "tb"
    monkeypatch.setattr(codeteam_queue_batch, "failing_test_callees",
                        Mock(return_value=[[["src/b.py", None]], []]))
    verdict = Mock(return_value=True)
    monkeypatch.setattr(codeteam_queue_batch, "batch_verdict", verdict)
    assert queue_batch(f.team, f.paths, f.land) is True
    result = verdict.call_args.args[3]["results"][1]
    assert result["frames"] == [["src/b.py", 7], ["src/b.py", None]]
    assert "callees_incomplete" not in result


def test_conflicting_entry_goes_back_and_other_entry_is_tested_and_landed(fixture):
    f = fixture
    f.state["conflict"] = "a2"
    assert queue_batch(f.team, f.paths, f.land) is True
    assert [name for name, _ in f.landed] == ["b"]
    assert f.runs == [("integ+tb", {"B"}, {"shared", "src/b"})]
    f.land.landing_conflict.assert_called_once()
    args = f.land.landing_conflict.call_args.args
    assert args[0:2] == (f.team, f.paths[0])
    assert [r["wo"] for r in args[2]] == ["a", "a2"]
    assert args[3:] == (["bad.py"], "a2", ["prior"])


def test_moved_landing_still_lands_all_ready_entries(fixture):
    f = fixture
    f.state["moved"] = True
    assert queue_batch(f.team, f.paths, f.land) is True
    assert [name for name, _ in f.landed] == ["a", "b"]
    assert not any(path.exists() for path in f.paths)


def test_landing_conflict_does_not_stop_later_entry(fixture):
    f = fixture
    original = f.land.land_entry.side_effect
    f.land.land_entry.side_effect = lambda team, path: 2 if path == f.paths[0] else original(team, path)
    assert queue_batch(f.team, f.paths, f.land) is True
    assert [name for name, _ in f.landed] == ["b"]
    assert [call.args[1] for call in f.land.land_entry.call_args_list] == f.paths


def test_landing_refusal_stops_before_later_entry(fixture):
    f = fixture
    f.land.land_entry.side_effect = lambda team, path: 5
    assert queue_batch(f.team, f.paths, f.land) is False
    assert f.landed == []
    assert [call.args[1] for call in f.land.land_entry.call_args_list] == [f.paths[0]]


def test_conflict_note_uses_integration_tip_and_earlier_batch_causes(fixture):
    f = fixture
    f.land.merge_landing_member = Mock(side_effect=lambda team, base, cur, rec, tip:
                                       (None, ["shared"]) if rec["wo"] == "b" else (cur + "+" + tip, []))
    assert queue_batch(f.team, f.paths, f.land) is True
    f.land.conflicting_landings.assert_called_once_with(f.team, "base", "integ", ["shared"])
    assert f.land.landing_conflict.call_args.args[5] == ["prior", "a", "a2"]


def test_send_back_request_names_integration_tip(fixture):
    f = fixture
    f.state["fail"] = "tb"
    assert queue_batch(f.team, f.paths, f.land) is True
    assert f.land.integration_send_back.call_args.args[1] == "integration"
    assert "integration" in f.team.notify.call_args.args[2]


def test_first_whole_batch_slow_flag_is_reported_once(fixture):
    f = fixture
    f.state["fail"] = "tb"
    assert queue_batch(f.team, f.paths, f.land) is True
    f.land.report_slow_tests.assert_called_once()
    args = f.land.report_slow_tests.call_args.args
    assert args[0] is f.team and args[1] == {"total_s": 901}
    assert args[3] == "Stage 2"
    assert args[4] == {"wo": "a", "zone": "A", "stage": 2, "commit": "integ+ta+ta2+tb"}
    assert set(args[5]) == {"src/a", "src/b", "shared"}


def test_compile_failure_never_runs_integration_steps(fixture):
    f = fixture
    f.state["compile_fail"] = True
    assert queue_batch(f.team, f.paths, f.land) is True
    assert f.land.step_results.call_args_list
    assert all(call.kwargs.get("group") == "compile" for call in f.land.step_results.call_args_list)
    assert [name for name, _ in f.landed] == ["a"]
    assert not f.paths[1].exists()


def test_conflict_with_an_earlier_batch_entry_names_its_work_orders(fixture):
    f = fixture
    f.land.merge_landing_member = Mock(side_effect=lambda team, base, cur, rec, tip:
                                       (None, ["shared"]) if rec["wo"] == "b" else (cur + "+" + tip, []))
    assert queue_batch(f.team, f.paths, f.land) is True
    assert [name for name, _ in f.landed] == ["a"]
    args = f.land.landing_conflict.call_args.args
    assert args[1] == f.paths[1]
    assert args[3:] == (["shared"], "b", ["prior", "a", "a2"])


def test_entry_held_while_its_group_ran_is_not_landed(fixture):
    f = fixture
    def hold_b(team_, commit, rows):
        entry = json.loads(f.paths[1].read_text())
        f.paths[1].write_text(json.dumps(entry | {"hold": True}))
    f.land.keep_recheck_logs = Mock(side_effect=hold_b)
    assert queue_batch(f.team, f.paths, f.land) is True
    assert [name for name, _ in f.landed] == ["a"]
    assert f.paths[1].exists()


def failing_checkout(f):
    f.land.itest_checkout = Mock(side_effect=CheckoutFailed("integ+ta+ta2+tb", "fatal: index.lock exists"))


def test_failed_checkout_lands_and_sends_back_nothing_and_notes_once(fixture):
    f = fixture
    failing_checkout(f)
    assert queue_batch(f.team, f.paths, f.land) is False
    assert f.landed == []
    assert all(path.exists() for path in f.paths)
    assert all(rec["queued"] == "now" and rec["stage2"] == [] for rec in f.records.values())
    f.land.integration_send_back.assert_not_called()
    f.land.step_results.assert_not_called()
    f.land.itest_checkout.assert_called_once()
    f.team.notify.assert_called_once()
    recipient, kind, text = f.team.notify.call_args.args
    assert (recipient, kind) == ("Coord-orc", "NOTE")
    assert all(s in text for s in ("a, a2, b", "fatal: index.lock exists"))
    assert (f.team.dir / "queue-batch-checkout.json").exists()


def test_still_failing_checkout_sends_no_new_note(fixture):
    f = fixture
    failing_checkout(f)
    assert queue_batch(f.team, f.paths, f.land) is False
    assert queue_batch(f.team, f.paths, f.land) is False
    f.team.notify.assert_called_once()
    assert f.landed == []


def test_checkout_that_works_again_clears_the_episode_and_lands(fixture):
    f = fixture
    working = f.land.itest_checkout
    failing_checkout(f)
    assert queue_batch(f.team, f.paths, f.land) is False
    f.land.itest_checkout = working
    assert queue_batch(f.team, f.paths, f.land) is True
    assert [name for name, _ in f.landed] == ["a", "b"]
    assert not (f.team.dir / "queue-batch-checkout.json").exists()
