import contextlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_land_one import land_one


@pytest.fixture
def queued(tmp_path):
    path = tmp_path / "entry.json"
    entry = {"wo": "first", "wos": ["first", "second"], "tip": "a",
             "tips": [["first", "a"], ["second", "b"]],
             "integration": "owed", "review": "land"}
    path.write_text(json.dumps(entry))
    state = {"locked": False, "events": []}
    team = SimpleNamespace(wo_file=lambda wo: tmp_path / f"{wo}.json")

    @contextlib.contextmanager
    def lock(team_):
        assert team_ is team
        assert not state["locked"]
        state["locked"] = True
        try:
            yield
        finally:
            state["locked"] = False

    def prune(team_):
        assert team_ is team and state["locked"]
        state["events"].append("prune")

    def lookup(team_, wo):
        assert team_ is team and state["locked"]
        state["events"].append("lookup")
        return path if wo in entry["wos"] and path.exists() else None

    def die(message):
        raise SystemExit(message)

    def members(value):
        return [(wo, tip) for wo, tip in value["tips"]]

    land = SimpleNamespace(Lock=lock, prune_queue=Mock(side_effect=prune),
                           entry_path=Mock(side_effect=lookup), die=Mock(side_effect=die),
                           land_entry=Mock(), queue_batch=Mock(), entry_members=members,
                           REFUSED=5, GATE=3)
    return SimpleNamespace(team=team, land=land, path=path, entry=entry, state=state)


def test_missing_entry_is_pruned_then_refused(queued):
    queued.path.unlink()
    with pytest.raises(SystemExit, match="first is not queued"):
        land_one(queued.team, "first", queued.land)
    assert queued.state["events"] == ["prune", "lookup"]
    queued.land.die.assert_called_once_with("first is not queued")
    queued.land.land_entry.assert_not_called()
    queued.land.queue_batch.assert_not_called()
    assert not queued.state["locked"]


def test_entry_without_integration_lands_under_lock(queued):
    del queued.entry["integration"]
    queued.path.write_text(json.dumps(queued.entry))

    def legacy(team, path):
        assert queued.state["locked"]
        assert (team, path) == (queued.team, queued.path)
        path.unlink()
        return 3

    queued.land.land_entry.side_effect = legacy
    assert land_one(queued.team, "first", queued.land) == 3
    assert not queued.path.exists()
    assert queued.state["events"] == ["prune", "lookup"]
    queued.land.queue_batch.assert_not_called()
    assert not queued.state["locked"]


@pytest.mark.parametrize("review", ["pending", "send-back"])
def test_owed_entry_without_land_review_is_refused(queued, review):
    queued.entry["review"] = review
    queued.path.write_text(json.dumps(queued.entry))
    assert land_one(queued.team, "first", queued.land) == 5
    assert queued.path.exists()
    queued.land.queue_batch.assert_not_called()
    queued.land.land_entry.assert_not_called()


def test_held_owed_entry_is_refused_with_land_hold_message(queued, capsys):
    queued.entry["hold"] = True
    queued.path.write_text(json.dumps(queued.entry))
    assert land_one(queued.team, "first", queued.land) == 5
    assert "land-hold" in capsys.readouterr().err
    assert queued.path.exists()
    queued.land.queue_batch.assert_not_called()
    queued.land.land_entry.assert_not_called()


def test_owed_entry_runs_alone_outside_lock_and_all_members_landed(queued):
    other = queued.path.parent / "other.json"
    other.write_text('{"wo": "other"}')

    def batch(team, paths, land):
        assert not queued.state["locked"]
        assert team is queued.team and land is queued.land
        assert paths == [queued.path]
        queued.path.unlink()
        for wo in ("first", "second"):
            team.wo_file(wo).with_suffix(".landed.json").write_text("{}")

    queued.land.queue_batch.side_effect = batch
    assert land_one(queued.team, "second", queued.land) == 0
    queued.land.queue_batch.assert_called_once_with(queued.team, [queued.path], queued.land)
    queued.land.land_entry.assert_not_called()
    assert other.exists()


def test_owed_entry_remaining_in_queue_is_refused(queued):
    queued.land.queue_batch.return_value = False
    assert land_one(queued.team, "first", queued.land) == 5
    assert queued.path.exists()
    queued.land.queue_batch.assert_called_once_with(queued.team, [queued.path], queued.land)


def test_removed_entry_with_missing_member_record_is_gate(queued):
    def sent_back(team, paths, land):
        queued.path.unlink()
        team.wo_file("first").with_suffix(".landed.json").write_text("{}")

    queued.land.queue_batch.side_effect = sent_back
    assert land_one(queued.team, "first", queued.land) == 3
    assert not queued.path.exists()
    queued.land.queue_batch.assert_called_once_with(queued.team, [queued.path], queued.land)


def test_entry_disappearing_during_batch_is_tolerated(queued):
    def vanished(team, paths, land):
        queued.path.unlink()
        raise FileNotFoundError(queued.path)

    queued.land.queue_batch.side_effect = vanished
    assert land_one(queued.team, "first", queued.land) == 3
    queued.land.queue_batch.assert_called_once_with(queued.team, [queued.path], queued.land)
