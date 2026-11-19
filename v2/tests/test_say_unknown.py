"""`unknown_names` lists the names in a `say` that would reach no one. A unit test: the team is a fake
with the three methods it reads."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2.say_unknown import unknown_names  # noqa: E402

ORC = SimpleNamespace(key="orc")
KONG = SimpleNamespace(key="kong")
LANE = SimpleNamespace(key="v2")


class FakeTeam:
    def is_user(self, to):
        return to.strip().lower() == "owner"

    def session(self, name):
        return {"Orc-Codeteam": ORC, "Kong": KONG, "v2": LANE}.get(name)

    def resolve_recipient(self, to, channel):
        return self.session(to) or self.session(channel) or ORC


def no_other_team(_name):
    return False


def test_a_name_no_session_has_that_falls_back_to_the_sender_is_unknown():
    assert unknown_names(FakeTeam(), ["Orc-Other"], ORC, "general", no_other_team) == ["Orc-Other"]


def test_only_the_unknown_names_of_a_list_are_returned_in_order():
    names = ["Kong", "Designer-Codeteam", "Orc-Other"]
    assert unknown_names(FakeTeam(), names, ORC, "general", no_other_team) == ["Designer-Codeteam", "Orc-Other"]


def test_codeteam_the_creator_the_user_and_another_teams_orchestrator_are_not_unknown():
    names = ["codeteam", "creator", "Creator", "Owner", "Orc-Acme"]
    assert unknown_names(FakeTeam(), names, ORC, "general", lambda n: n == "Orc-Acme") == []


def test_a_name_that_falls_back_to_someone_else_is_not_unknown():
    # From Kong, an unknown name falls back to the orchestrator, who reads it: delivered, as before.
    assert unknown_names(FakeTeam(), ["Orc-Codeteam"], KONG, "general", no_other_team) == []
    # On a lane's channel the fallback is the lane, not the sending orchestrator.
    assert unknown_names(FakeTeam(), ["Orc-Codeteam"], ORC, "v2", no_other_team) == []


def test_a_sender_that_is_no_session_has_no_unknown_names():
    assert unknown_names(FakeTeam(), ["Orc-Codeteam"], None, "general", no_other_team) == []


def test_the_sender_named_by_its_own_name_is_not_unknown():
    # A session messaging itself by name is skipped by say's never-the-sender rule, not refused here.
    assert unknown_names(FakeTeam(), ["Orc-Codeteam"], ORC, "general", no_other_team) == []
