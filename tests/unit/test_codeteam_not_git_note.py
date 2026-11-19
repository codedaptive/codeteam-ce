import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_not_git_note import not_git_note


class FakeTeam:
    def __init__(self, orchestrator=None):
        self.config = {"orchestrator": orchestrator} if orchestrator else {}
        self.saved, self.told = [], []

    def c(self, key, default=None):
        return self.config.get(key, default)

    def save_wo(self, rec):
        self.saved.append(dict(rec))

    def notify(self, to, kind, text):
        self.told.append((to, kind, text))


def test_first_note_marks_saves_and_tells_the_orchestrator():
    team = FakeTeam()
    rec = {"wo": "w1", "tree": "/t/w1"}
    not_git_note(team, rec, "w1", Path("/t/w1"), "fatal: not a git repository", lambda: "T1")
    assert team.saved == [{"wo": "w1", "tree": "/t/w1", "not_a_git_tree": "T1"}]
    assert team.told == [("orc", "NOTE", "Work order w1: its tree /t/w1 is not a git work tree (fatal: not a git "
                          "repository), so the landing runner's idle clean skips it. Move the folder aside, or "
                          "retire the work order.")]


def test_a_named_orchestrator_gets_the_note():
    team = FakeTeam(orchestrator="Orc-X")
    not_git_note(team, {"wo": "w1"}, "w1", Path("/t/w1"), "fatal", lambda: "T1")
    assert [to for to, _, _ in team.told] == ["Orc-X"]


def test_a_marked_record_is_not_told_again():
    team = FakeTeam()
    not_git_note(team, {"wo": "w1", "not_a_git_tree": "T0"}, "w1", Path("/t/w1"), "fatal", lambda: "T1")
    assert team.saved == [] and team.told == []


def test_the_error_is_cut_to_160_characters():
    team = FakeTeam()
    not_git_note(team, {"wo": "w1"}, "w1", Path("/t/w1"), "e" * 200, lambda: "T1")
    assert "(" + "e" * 160 + ")" in team.told[0][2]
