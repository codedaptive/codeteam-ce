import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
import codeteam_batch_verdict as verdict_module


def _setup(tmp_path, monkeypatch):
    team = SimpleNamespace(repo=tmp_path / "repo")
    kept = [(tmp_path / "a.json", {"tips": [["a", "ta"], ["a2", "ta2"]]}),
            (tmp_path / "b.json", {"tips": [["b", "tb"]]}),
            (tmp_path / "c.json", {"tips": [["c", "tc"]]})]
    diffs = {"base...ta": '--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n+x\n',
             "base...ta2": '--- a/a2.py\n+++ b/a2.py\n@@ -3 +3 @@\n+x\n',
             "base...tb": '--- a/b.py\n+++ b/b.py\n@@ -7 +7 @@\n+x\n',
             "base...tc": '--- a/c.py\n+++ b/c.py\n@@ -2 +2 @@\n+x\n'}
    def out(repo, diff, context, revision):
        assert (repo, diff, context) == (team.repo, "diff", "-U0")
        return diffs[revision]
    land = SimpleNamespace(out=Mock(side_effect=out), entry_members=lambda entry: entry["tips"])
    run = {"base": "base", "commit": "batch", "rows": [], "results": [
        {"name": "pass", "outcome": "PASS", "frames": [["a.py", 1]]},
        {"name": "fail", "outcome": "FAIL", "frames": [["b.py", 7], ["b.py", 7]]}]}
    landed, sent, finding = Mock(return_value=True), Mock(), Mock()
    monkeypatch.setattr(verdict_module, "batch_landed", landed)
    monkeypatch.setattr(verdict_module, "batch_send_back", sent)
    monkeypatch.setattr(verdict_module, "batch_fix_finding", finding)
    return team, land, kept, run, landed, sent, finding


def test_only_matched_entry_is_sent_back_and_rest_land(tmp_path, monkeypatch):
    team, land, kept, run, landed, sent, finding = _setup(tmp_path, monkeypatch)
    assert verdict_module.batch_verdict(team, land, kept, run) is True
    assert sent.call_count == 1
    assert sent.call_args.args[:3] == (team, land, kept[1])
    assert [row["name"] for row in sent.call_args.args[3]["results"] if row["outcome"] != "PASS"] == ["fail"]
    assert sent.call_args.args[4] == [["b.py", 7]]
    landed.assert_called_once_with(team, land, [kept[0], kept[2]], run)
    finding.assert_not_called()
    assert {call.args[3] for call in land.out.call_args_list} == {"base...ta", "base...ta2", "base...tb", "base...tc"}


def test_second_member_diff_can_match_its_entry(tmp_path, monkeypatch):
    team, land, kept, run, landed, sent, finding = _setup(tmp_path, monkeypatch)
    run["results"][1]["frames"] = [["a2.py", 3]]
    assert verdict_module.batch_verdict(team, land, kept, run) is True
    assert sent.call_count == 1
    assert sent.call_args.args[:3] == (team, land, kept[0])
    assert [row["name"] for row in sent.call_args.args[3]["results"] if row["outcome"] != "PASS"] == ["fail"]
    assert sent.call_args.args[4] == [["a2.py", 3]]
    landed.assert_called_once_with(team, land, [kept[1], kept[2]], run)
    finding.assert_not_called()


def test_no_match_lands_every_entry_and_opens_fix_finding(tmp_path, monkeypatch):
    team, land, kept, run, landed, sent, finding = _setup(tmp_path, monkeypatch)
    run["results"][1]["frames"] = [["other.py", 100]]
    assert verdict_module.batch_verdict(team, land, kept, run) is True
    sent.assert_not_called()
    landed.assert_called_once_with(team, land, kept, run)
    assert finding.call_count == 1
    assert finding.call_args.args[:3] == (team, land, kept)
    assert [row["name"] for row in finding.call_args.args[3]["results"] if row["outcome"] != "PASS"] == ["fail"]


def test_mixed_failures_send_only_the_matching_step_and_frames_to_entry(tmp_path, monkeypatch):
    team, land, kept, run, landed, sent, finding = _setup(tmp_path, monkeypatch)
    kept = kept[:2]
    run["results"] = [
        {"name": "S1", "outcome": "FAIL", "frames": [["a.py", 1]], "failing": ["test_a"]},
        {"name": "S2", "outcome": "FAIL", "frames": [], "failing": ["test_b"]},
    ]
    assert verdict_module.batch_verdict(team, land, kept, run) is True
    assert sent.call_count == 1
    args = sent.call_args.args
    assert args[:3] == (team, land, kept[0])
    assert [row["name"] for row in args[3]["results"] if row["outcome"] != "PASS"] == ["S1"]
    assert args[4] == [["a.py", 1]]
    landed.assert_called_once_with(team, land, [kept[1]], run)


def test_mixed_failures_open_a_finding_only_for_the_unmatched_step(tmp_path, monkeypatch):
    team, land, kept, run, landed, sent, finding = _setup(tmp_path, monkeypatch)
    kept = kept[:2]
    run["results"] = [
        {"name": "S1", "outcome": "FAIL", "frames": [["a.py", 1]], "failing": ["test_a"]},
        {"name": "S2", "outcome": "FAIL", "frames": [], "failing": ["test_b"]},
    ]
    assert verdict_module.batch_verdict(team, land, kept, run) is True
    assert finding.call_count == 1
    args = finding.call_args.args
    assert args[:3] == (team, land, kept)
    assert [row["name"] for row in args[3]["results"] if row["outcome"] != "PASS"] == ["S2"]
    landed.assert_called_once_with(team, land, [kept[1]], run)


def test_landing_refusal_is_returned(tmp_path, monkeypatch):
    team, land, kept, run, landed, sent, finding = _setup(tmp_path, monkeypatch)
    landed.return_value = False
    assert verdict_module.batch_verdict(team, land, kept, run) is False
