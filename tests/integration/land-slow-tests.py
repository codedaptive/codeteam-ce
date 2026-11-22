#!/usr/bin/env -S python3 -u
"""The slow-test rule (2026-11-14): the slow-tests flag, its follow-up record and its closing, each through the real
findings lock on a temp folder's real files (slow-tests.json, integration-results.jsonl, the findings files); git,
notify and the clock are fakes. Real shell steps also exercise run-time parsing. Unit tests are in
tests/unit/land-slow-tests.py."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
loader = importlib.machinery.SourceFileLoader("cl_slow", os.environ.get("CODETEAM_LAND", str(ROOT / "bin" / "codeteam-land")))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)


def stamped(batches):
    """A step_results fake: the next batch, each row carrying the group keyword as the real one stamps it."""
    batches = iter(batches)
    return lambda *args, **kw: [row | ({"group": kw["group"]} if "group" in kw else {}) for row in next(batches)]


def team_at(path):
    return SimpleNamespace(dir=path, manifest="team.toml", zones={"cli": ["bin"], "gadget": ["gadget"]},
                           m={"assistants": [{"name": "Designer", "role": "designer"}]},
                           c=lambda key, default: "Orchestrator", notify=Mock(), log=Mock(),
                           save_wo=Mock(), repo=path, integration="integration")


def flag():
    return {"total_s": 960.0, "limit_s": 900, "steps": [
        {"step": "tests cli (bin)", "run_s": 600.0, "queued_s": 200.0},
        {"step": "unit tests (tests/unit)", "run_s": 360.0, "queued_s": 0.0}]}


def rows():
    return [{"step": "tests cli (bin)", "result": "pass", "seconds": 800.0, "queued": 200},
            {"step": "unit tests (tests/unit)", "result": "pass", "seconds": 360.0}]


class NoteContaining:
    def __init__(self, *parts):
        self.parts = parts

    def __eq__(self, actual):
        return isinstance(actual, str) and all(part in actual for part in self.parts)

    def __repr__(self):
        return f"NOTE containing {self.parts!r}"


def note(head, stage, suffix):
    return NoteContaining(f"SLOW TESTS {head}: {stage} tests ran 16.0 min of run time",
                          "waits excluded", "limit 15",
                          "slowest: tests cli (bin) 10.0 min, unit tests (tests/unit) 6.0 min",
                          suffix, "a flag, not a hold")


def request(wo="w1", stage=2, commit="abcdefghij", zone="cli", ident="slow#1"):
    return (f"SLOW TESTS FOLLOW-UP {ident} | zone {zone} | ran in {wo} at Stage {stage}, commit {commit} | "
            "tests ran 16.0 min of run time (limit 15) | slowest: tests cli (bin) 10.0 min, "
            "unit tests (tests/unit) 6.0 min. Route it as a work order: find why these tests take that long "
            "and write it up in a report; the team's designer reviews it and takes it to the owner if it needs a rule "
            f"change. Land it with codeteam-land team.toml land <wo> --fixes {ident}, which closes the follow-up. "
            "Nothing is held.")


def test_slow_followups_open_deduplicate_and_sequence():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); source = {"wo": "w1", "stage": 2, "commit": "abcdefghijk"}
        entry, opened = cl.open_slow_followup(team, flag(), source, "NOW", [])
        assert opened and entry == {"id": "slow#1", "zone": "cli", "opened": "NOW", "from": source,
                                    "total_s": 960.0, "steps": flag()["steps"], "state": "open",
                                    "closed": None, "closed_by": None}
        again, opened = cl.open_slow_followup(team, flag(), source, "LATER", [])
        assert not opened and again == entry
        other = {"total_s": 960.0, "limit_s": 900, "steps": [
            {"step": "tests gadget", "run_s": 960.0, "queued_s": 0.0}]}
        second, opened = cl.open_slow_followup(team, other, source, "LATER", [])
        assert opened and second["id"] == "slow#2" and second["zone"] == "gadget"
        assert json.loads((team.dir / "slow-tests.json").read_text()) == [entry, second]


def test_a_flag_on_the_slowest_step_a_landed_report_covers_opens_nothing_for_24_hours():
    # WidgetCoreKit's slow#5, #6 and #7 were one cause, each a new lane turn and report.
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); source = {"wo": "w2", "stage": 5, "commit": "bcdefghijkl"}
        reported = {"id": "slow#1", "zone": "cli", "opened": "2026-11-15T00:58:00-06:00", "from": {"wo": "w1"},
                    "total_s": 960.0, "steps": flag()["steps"], "state": "closed",
                    "closed": "2026-11-15T01:07:00-06:00", "closed_by": "cli-slow-1-report"}
        (team.dir / "slow-tests.json").write_text(json.dumps([reported]))
        with patch.object(cl, "now", return_value="2026-11-15T02:00:00-06:00"):
            cl.report_slow_tests(team, flag(), "w2", "Stage 5", source, [])
        assert team.notify.call_args_list == [call("Orchestrator", "NOTE", note(
            "w2", "Stage 5", "same slowest step as slow#1, whose report landed in cli-slow-1-report: no new "
                             "follow-up within 24 h of it, recorded on slow#1"))]
        saved = json.loads((team.dir / "slow-tests.json").read_text())
        assert saved == [reported | {"seen_again": [{"when": "2026-11-15T02:00:00-06:00", "from": source,
                                                     "total_s": 960.0}]}]
        entry, opened = cl.open_slow_followup(team, flag(), source, "2026-11-16T01:07:01-06:00", [])
        assert opened and entry["id"] == "slow#2", "a day after the report, the same step opens a new follow-up"


def test_a_wide_landings_followup_opens_for_the_work_orders_own_zone():
    # The slowest tests' zone holds no changed file, so the
    # follow-up is the work order's zone's (cli), and the same flag finds it open there.
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); source = {"wo": "w1", "zone": "cli", "stage": 2, "commit": "abcdefghijk"}
        wide = {"total_s": 960.0, "limit_s": 900, "steps": [{"step": "tests gadget", "run_s": 960.0,
                                                             "queued_s": 0.0}]}
        entry, opened = cl.open_slow_followup(team, wide, source, "NOW", ["bin/x"])
        assert opened and entry["zone"] == "cli" and entry["from"] == source
        again, opened = cl.open_slow_followup(team, wide, source, "LATER", ["bin/x"])
        assert not opened and again == entry
        own, opened = cl.open_slow_followup(team, wide, source, "LATER", ["gadget/y"])
        assert opened and own["id"] == "slow#2" and own["zone"] == "gadget"

def test_report_slow_tests_notifies_and_deduplicates():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); source = {"wo": "w1", "stage": 2, "commit": "abcdefghijk"}
        with patch.object(cl, "now", return_value="NOW"):
            cl.report_slow_tests(team, flag(), "w1", "Stage 2", source, [])
            cl.report_slow_tests(team, flag(), "w1", "Stage 2", source, [])
        assert team.notify.call_args_list == [
            call("Coord-cli", "REQUEST", request()),
            call("Orchestrator", "NOTE", note("w1", "Stage 2", "follow-up slow#1 opened for zone cli")),
            call("Orchestrator", "NOTE", note("w1", "Stage 2", "follow-up slow#1 is already open for zone cli"))]


def test_slow_report_note_explains_parallel_steps():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); source = {"wo": "w1", "stage": 2, "commit": "abcdefghijk"}
        with patch.object(cl, "now", return_value="NOW"):
            cl.report_slow_tests(team, flag(), "w1", "Stage 2", source, [])
        notes = [call.args[2] for call in team.notify.call_args_list if call.args[1] == "NOTE"]
        assert len(notes) == 1
        assert "side by side" in notes[0].lower()


def test_orc_followup_goes_to_orchestrator():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); f = {"total_s": 901.0, "limit_s": 900, "steps": [
            {"step": "unit tests (tests/unit)", "run_s": 901.0, "queued_s": 0.0}]}
        with patch.object(cl, "now", return_value="NOW"):
            cl.report_slow_tests(team, f, "w1", "Stage 2", {"wo": "w1", "stage": 2, "commit": "abcdefghijk"}, [])
        assert team.notify.call_args_list[0] == call("Orchestrator", "REQUEST",
            "SLOW TESTS FOLLOW-UP slow#1 | zone orc | ran in w1 at Stage 2, commit abcdefghij | "
            "tests ran 15.0 min of run time (limit 15) | slowest: unit tests (tests/unit) 15.0 min. "
            "Route it as a work order: find why these tests take that long and write it up in a report; "
            "the team's designer reviews it and takes it to the owner if it needs a rule change. Land it with "
            "codeteam-land team.toml land <wo> --fixes slow#1, which closes the follow-up. Nothing is held.")


def stage2_records(stage_rows, old=True):
    return [{"wo": wo, "zone": "cli", "tree": f"tree{n}", "stage2": stage_rows} | ({"slow_tests": {"old": True}} if old else {})
            for n, wo in ((1, "w1"), (2, "w2"))]


def run_stage2(team, records, check=(["cli"], ["cli"])):
    """check_and_queue over the two records; check is check_combined_members' answer, or the exception it raises."""
    with contextlib.ExitStack() as stack:
        for name, value in {"checked_members": [(r, None) for r in records], "out": "abcdefghijk",
                            "merge_checked_base": None, "other_member_heads": [], "changed_files": [], "own_base": "base", "now": "NOW",
                            "queue_notices": None, "queue_entry": {"review": "pending"},
                            "stage3_request": "review"}.items():
            stack.enter_context(patch.object(cl, name, return_value=value))
        stack.enter_context(patch.object(cl, "check_combined_members",
                                         **({"side_effect": check} if isinstance(check, BaseException) else {"return_value": check})))
        stack.enter_context(patch.object(cl, "Lock", return_value=contextlib.nullcontext()))
        queue = stack.enter_context(patch.object(cl, "queue_stage3", return_value={"Reviewer": ["w1"]}))
        with contextlib.redirect_stdout(io.StringIO()):
            cl.check_and_queue(team, SimpleNamespace(wo="w1"), ["w1", "w2"])
        queue.assert_called_once_with(team, records, {"review": "pending"}, "NOW")
    return records


def test_stage2_saves_flag_and_still_queues():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); records = run_stage2(team, stage2_records(rows()))
        assert all(r["slow_tests"] == flag() for r in records)
        assert team.save_wo.call_count == 2
        assert team.notify.call_args_list == [call("Reviewer", "REQUEST", "review"),
            call("Coord-cli", "REQUEST", request()),
            call("Orchestrator", "NOTE", note("w1, w2", "Stage 2", "follow-up slow#1 opened for zone cli"))]


def test_notices_name_only_the_three_slowest_steps():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); f = {"total_s": 1080.0, "limit_s": 900, "steps": [
            {"step": "tests cli (bin)", "run_s": 600.0, "queued_s": 0.0},
            {"step": "unit tests (tests/unit)", "run_s": 300.0, "queued_s": 0.0},
            {"step": "tests gadget", "run_s": 120.0, "queued_s": 0.0},
            {"step": "integration tests (tests/integration)", "run_s": 60.0, "queued_s": 0.0}]}
        with patch.object(cl, "now", return_value="NOW"):
            cl.report_slow_tests(team, f, "w1", "Stage 2", {"wo": "w1", "stage": 2, "commit": "abcdefghijk"}, [])
        assert team.notify.call_args_list == [
            call("Coord-cli", "REQUEST",
                 "SLOW TESTS FOLLOW-UP slow#1 | zone cli | ran in w1 at Stage 2, commit abcdefghij | "
                 "tests ran 18.0 min of run time (limit 15) | slowest: tests cli (bin) 10.0 min, "
                 "unit tests (tests/unit) 5.0 min, tests gadget 2.0 min. Route it as a work order: find why "
                 "these tests take that long and write it up in a report; the team's designer reviews it and takes "
                 "it to the owner if it needs a rule change. Land it with codeteam-land team.toml land <wo> --fixes "
                 "slow#1, which closes the follow-up. Nothing is held."),
            call("Orchestrator", "NOTE", NoteContaining(
                 "SLOW TESTS w1: Stage 2 tests ran 18.0 min of run time", "waits excluded", "limit 15",
                 "slowest: tests cli (bin) 10.0 min, unit tests (tests/unit) 5.0 min, tests gadget 2.0 min",
                 "follow-up slow#1 opened for zone cli", "a flag, not a hold"))]


def run_recheck(team, outcome, landed=None):
    row = {"time": "then", "wo": "w1", "M": "abcdefghijk", "overlapping": [], "zones": ["cli"]}
    results = [{"name": "tests cli (bin)", "outcome": outcome, "seconds": 800.0, "queued": 200},
               {"name": "unit tests (tests/unit)", "outcome": "PASS", "seconds": 360.0}]
    with contextlib.ExitStack() as stack:
        for name, value in {"itest_checkout": "tree", "recheck_steps": ([], ["test"]), "team_env": {},
                            "keep_recheck_logs": None, "landed_rec": landed or {}, "now": "NOW"}.items():
            stack.enter_context(patch.object(cl, name, return_value=value))
        stack.enter_context(patch.object(cl, "step_results", side_effect=stamped([[], results])))
        apply = stack.enter_context(patch.object(cl, "apply_recheck_findings"))
        complete = stack.enter_context(patch.object(cl, "complete_recheck"))
        result = cl.recheck_one(team, [row])
    return row, result, apply, complete


def check_recheck(outcome):
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); row, result, apply, complete = run_recheck(
            team, outcome, {"zone": "cli", "stage2_tests_s": 960.0, "files": ["bin/example"]})
        expected = [{"name": "tests cli (bin)", "result": outcome.lower(), "seconds": 800.0, "queued": 200, "group": "integration"},
                    {"name": "unit tests (tests/unit)", "result": "pass", "seconds": 360.0, "group": "integration"}]
        assert result["tests"] == expected and result["slow_tests"] == flag()
        assert json.loads((team.dir / "integration-results.jsonl").read_text()) == result
        apply.assert_called_once()
        assert apply.call_args.args[0] is team
        assert apply.call_args.args[1]["M"] == row["M"]
        assert callable(apply.call_args.args[2])
        assert apply.call_args.args[3:] == (expected, "NOW")
        complete.assert_called_once_with(team, row, "NOW")
        assert team.notify.call_args_list == [call("Coord-cli", "REQUEST", request(stage=5)),
            call("Orchestrator", "NOTE", note("w1 recheck at M abcdefghij", "Stage 5", "follow-up slow#1 opened for zone cli"))]


def test_recheck_pass_flags_without_changing_results():
    check_recheck("PASS")


def test_recheck_failure_flags_without_changing_results():
    check_recheck("FAIL")


def test_recheck_unrecorded_stage2_only_notifies_load_without_followup_file():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        _, result, _, _ = run_recheck(team, "PASS", {})
        assert result["slow_tests"] == flag()
        assert team.notify.call_args_list == [call("Orchestrator", "NOTE", note(
            "w1 recheck at M abcdefghij", "Stage 5", "load, not a follow-up: no work order it covers had Stage 2 tests over 15 min (w1 Stage 2 not recorded)"))]
        assert not (team.dir / "slow-tests.json").exists()


def check_bookkeeping(recheck, designer):
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        if not designer:
            team.m["assistants"] = []
        path = team.dir / "slow-tests.json"
        path.write_text(json.dumps([{"id": "slow#1", "zone": "cli", "state": "open", "closed": None, "closed_by": None}]))
        with patch.object(cl, "docs_pass"), patch.object(cl, "now", return_value="NOW"):
            cl.member_bookkeeping(team, {"wo": "w1", "slow_fixes": ["slow#1"]}, {"recheck": recheck})
        assert json.loads(path.read_text()) == [{"id": "slow#1", "zone": "cli", "state": "closed", "closed": "NOW", "closed_by": "w1"}]
        team.notify.assert_called_once_with("Designer" if designer else "Orchestrator", "NOTE",
            "slow#1's report landed in w1: review it and take it to the owner if it needs a rule change")


def test_bookkeeping_closes_rechecked_followup_for_designer():
    check_bookkeeping(True, True)


def test_bookkeeping_closes_nonrechecked_followup_for_orchestrator():
    check_bookkeeping(False, False)


def test_set_sharing_a_slow_id_closes_it_once():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); path = team.dir / "slow-tests.json"
        path.write_text(json.dumps([{"id": "slow#1", "zone": "cli", "state": "open", "closed": None, "closed_by": None}]))
        with patch.object(cl, "docs_pass"), patch.object(cl, "now", return_value="NOW"):
            for wo in ("w1", "w2"):
                cl.member_bookkeeping(team, {"wo": wo, "slow_fixes": ["slow#1"]}, {"recheck": True})
        assert json.loads(path.read_text()) == [{"id": "slow#1", "zone": "cli", "state": "closed", "closed": "NOW", "closed_by": "w1"}]
        team.notify.assert_called_once_with("Designer", "NOTE",
            "slow#1's report landed in w1: review it and take it to the owner if it needs a rule change")


def test_slow_fix_does_not_close_stage7_finding():
    # A slow id carried through --fixes and a rechecked Stage 4 landing never closes a test finding, never lands in
    # rec["fixes"] and never reaches the findings files, so Stage 7 still blocks the open finding.
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); directory = team.dir / "findings"; directory.mkdir()
        (directory / "w1.json").write_text(json.dumps([{"id": "w1#1", "state": "open", "test": "test_one", "commits": ["C"]}]))
        (team.dir / "slow-tests.json").write_text(json.dumps([{"id": "slow#1", "zone": "cli", "state": "open",
                                                               "closed": None, "closed_by": None}]))
        rec = {"wo": "w2"}
        cl.tag_wo(team, rec, None, ["slow#1"])
        with patch.object(cl, "docs_pass"), patch.object(cl, "now", return_value="NOW"):
            cl.member_bookkeeping(team, rec, {"recheck": True})
        assert "fixes" not in rec and rec["slow_fixes"] == ["slow#1"]
        assert cl.unfixed_failures("C", cl.all_findings(team), {"w2": "C"}, lambda a, b: False) == ["w1#1"]
        assert sorted(p.name for p in directory.glob("*.json")) == ["w1.json"]


def test_step_results_extracts_job_and_cached_run_times():
    steps = [
        ("job", "printf '%s\\n' 'zone-tool: queued 12 s, ran 7 s (job abc)' "
                "'zone-test: PASS (exit 0); record /tmp/record.json'"),
        ("cached", "printf '%s\\n' 'zone-test: PASS at 14:23 already recorded for this exact code; not run again'"),
        ("plain", "printf '%s\\n' 'all passed'"),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        results = {r["name"]: r for r in cl.step_results(tmp, steps, os.environ.copy())}
    assert results["job"].get("queued") == 12
    assert results["job"].get("ran") == 7
    assert results["cached"].get("ran") == 0
    assert "queued" not in results["cached"]
    assert "ran" not in results["plain"]


def test_job_build_time_flows_through_stage2_and_is_excluded_from_test_run():
    command = ("printf '%s\\n' 'zone-tool: queued 12 s, ran 7 s (job abc, build 5 s)' "
               "'zone-test: PASS (exit 0); record /tmp/x.json'")
    with tempfile.TemporaryDirectory() as tmp:
        [result] = cl.step_results(tmp, [("tests cli (bin)", command)], os.environ.copy())
    assert result["build"] == 5
    assert result["ran"] == 7
    [row] = cl.stage2_record([result])
    assert row["build"] == 5
    assert cl.step_run_seconds(row) == 2


def test_real_step_results_and_stage2_record_keep_timing_and_records():
    with tempfile.TemporaryDirectory() as tmp:
        record = Path(tmp) / ".test-record.json"
        record.write_text('{"result":"PASS"}')
        command = f"printf '%s\\n' 'zone-test: PASS (exit 0); record {record}'"
        [result] = cl.step_results(tmp, [("tests cli (bin)", command)], os.environ.copy())
        assert "start" in result and "end" in result
        assert result["start"] <= result["end"]
        assert result["start"] == round(result["start"], 1)
        assert result["end"] == round(result["end"], 1)
        assert result.get("records") == [str(record)]
        [stage2] = cl.stage2_record([result])
        assert stage2.get("start") == result["start"]
        assert stage2.get("end") == result["end"]
        assert stage2.get("records") == [str(record)]


def test_step_results_stamps_group_when_given():
    steps = [("one", "printf 'a\\n'"), ("two", "printf 'b\\n'")]
    with tempfile.TemporaryDirectory() as tmp:
        for concurrent in (True, False):
            stamped_rows = cl.step_results(tmp, steps, os.environ.copy(), concurrent=concurrent, group="compile")
            assert [(r["name"], r["group"]) for r in stamped_rows] == [("one", "compile"), ("two", "compile")]
            plain = cl.step_results(tmp, steps, os.environ.copy(), concurrent=concurrent)
            assert [("group" in r) for r in plain] == [False, False]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("all passed")
