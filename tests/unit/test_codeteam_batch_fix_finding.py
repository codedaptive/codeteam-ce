import contextlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_batch_fix_finding import batch_fix_finding


def _setup(tmp_path, existing=()):
    items = list(existing)
    records = {"a": {"wo": "a", "feature": "old", "zone": "A"},
               "b": {"wo": "b", "feature": "new", "zone": "B"}}
    team = SimpleNamespace(integration="integration", manifest=tmp_path / "team.toml",
                           wo=lambda wo: records[wo], notify=Mock(), log=Mock())
    land = SimpleNamespace(FindingsLock=lambda team_: contextlib.nullcontext(),
                           entry_members=lambda entry: entry["tips"], all_findings=lambda team_: items,
                           landed_rec=lambda team_, wo: records[wo], feature_of=lambda rec: rec["feature"],
                           load_findings=lambda team_, feature: items,
                           save_findings=Mock(), now=lambda: "time", is_test_step=lambda name: name.startswith("tests "),
                           step_owner=lambda team_, name: "owner", zone_session=lambda team_, zone: "Coord-" + zone)
    kept = [(tmp_path / "a.json", {"tips": [["a", "ta"]]}),
            (tmp_path / "b.json", {"tips": [["b", "tb"]]})]
    run = {"commit": "1234567890abcdef", "results": [
        {"name": "tests owner", "outcome": "FAIL", "failing": ["test_bad"], "log": "/logs/fail"},
        {"name": "tests pass", "outcome": "PASS"}]}
    return team, land, kept, run, items


def test_unmatched_failure_opens_and_routes_finding_on_newest_feature(tmp_path):
    team, land, kept, run, items = _setup(tmp_path)
    batch_fix_finding(team, land, kept, run)
    assert len(items) == 1
    finding = items[0]
    assert {key: finding[key] for key in ("id", "by", "wos", "zone", "severity", "kind", "test", "Ms",
                                          "batch_commit")} == {
        "id": "new#1", "by": "queue-run", "wos": ["a", "b"], "zone": "owner", "severity": 2,
        "kind": "test", "test": "tests owner", "Ms": [], "batch_commit": "1234567890abcdef"}
    assert all(text in finding["what"] for text in ("1234567890", "test_bad", "/logs/fail"))
    assert "batch" in finding["what"] and "failure" in finding["what"]
    land.save_findings.assert_called_once_with(team, "new", items)
    recipient, kind, text = team.notify.call_args.args
    assert (recipient, kind) == ("Coord-owner", "REQUEST")
    assert "FIX-FORWARD new#1 | zone owner | test tests owner |" in text
    assert f"codeteam-land {team.manifest} land <wo> --fixes new#1" in text
    team.log.assert_not_called()


def test_existing_open_finding_gets_batch_commit_not_ms_without_new_finding_or_request(tmp_path):
    team, land, kept, run, items = _setup(tmp_path, [{"id": "old#1", "state": "open", "test": "tests owner",
                                                     "Ms": ["older"]}])
    batch_fix_finding(team, land, kept, run)
    assert len(items) == 1
    assert items[0]["Ms"] == ["older"]
    assert items[0]["batch_commit"] == "1234567890abcdef"
    team.notify.assert_not_called()
    land.save_findings.assert_called_once_with(team, "old", items)


def test_incomplete_callees_are_in_finding_what(tmp_path):
    team, land, kept, run, items = _setup(tmp_path)
    run["results"][0]["callees_incomplete"] = ["test_a", "test_b"]
    batch_fix_finding(team, land, kept, run)
    assert "; CodeGraph's callees were incomplete for test_a, test_b; matched on the stack alone" in items[0]["what"]


def test_incomplete_callees_are_in_finding_request(tmp_path):
    team, land, kept, run, _ = _setup(tmp_path)
    run["results"][0]["callees_incomplete"] = ["test_a", "test_b"]
    batch_fix_finding(team, land, kept, run)
    assert "; CodeGraph's callees were incomplete for test_a, test_b; matched on the stack alone" in team.notify.call_args.args[2]


def test_no_incomplete_callees_preserves_finding_what(tmp_path):
    team, land, kept, run, items = _setup(tmp_path)
    batch_fix_finding(team, land, kept, run)
    assert items[0]["what"] == (
        "tests owner fails in Stage 2's batch run at 1234567890 on integration's tip; no work "
        "order of the batch changed a file on the failure's path, so they landed; failing tests: test_bad; log: /logs/fail"
    )


def test_exception_is_logged_and_does_not_escape(tmp_path):
    team, land, kept, run, _ = _setup(tmp_path)
    land.all_findings = Mock(side_effect=ValueError("broken"))
    assert batch_fix_finding(team, land, kept, run) is None
    event = team.log.call_args.args[0]
    assert event["wos"] == ["a", "b"]
    assert event["time"] == "time"
    assert "broken" in event["batch_finding_error"]
