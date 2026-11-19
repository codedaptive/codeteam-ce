"""`say` records each message once (2026-11-12: a message for the creator was recorded twice, once as the creator's mail
and again as mail for no session, so general.log showed it twice). The store, herdr and the team are fakes."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2 import cli  # noqa: E402

ORC = SimpleNamespace(key="orc", display="Orc-Codeteam")
KONG = SimpleNamespace(key="kong", display="Kong")


class FakeStore:
    def __init__(self):
        self.rows, self.marks, self.rides = [], [], []

    def add(self, channel, sender, kind, to, recipient, text, ride=False):
        self.rows.append((to, recipient, text))
        self.rides.append(ride)
        return len(self.rows)

    def mark(self, mid, state, note):
        self.marks.append((mid, state, note))


class FakeTeam:
    product = "codeteam"
    manifest = "/nonexistent/teams/codeteam.toml"

    def __init__(self):
        self.t = SimpleNamespace(assistants={}, managed=lambda ch: False, orc_name=lambda: "Orc-Codeteam")
        self.logged = []

    def is_user(self, to):
        return False

    def session(self, name):
        return {"Orc-Codeteam": ORC, "Kong": KONG}.get(name)

    def resolve_recipient(self, to, channel):
        return self.session(to) or ORC

    def mirror_to_channel_log(self, channel, sender, kind, to, text):
        self.logged.append((kind, to, text))


class SayTest(unittest.TestCase):
    def say(self, to, kind="NOTE", text="hello", sender="Orc-Codeteam"):
        team, rt = FakeTeam(), SimpleNamespace(store=FakeStore(), herdr=SimpleNamespace(notify=lambda *a: None))
        with tempfile.TemporaryDirectory() as d, patch.object(cli, "CREATOR_INBOX", Path(d) / "creator-inbox.log"):
            cli.cmd_say(team, rt, SimpleNamespace(type=kind, text=[text], channel="general", sender=sender, to=to))
            inbox = (Path(d) / "creator-inbox.log").read_text().splitlines() if (Path(d) / "creator-inbox.log").exists() else []
        return team, rt.store, inbox

    def test_session_ride_is_recorded(self):
        team, rt = FakeTeam(), SimpleNamespace(store=FakeStore(), herdr=SimpleNamespace(notify=lambda *a: None))
        cli.cmd_say(team, rt, SimpleNamespace(type="NOTE", text=["hello"], channel="general",
                                              sender="Orc-Codeteam", to="Kong", ride=True))
        self.assertEqual(rt.store.rows, [("Kong", "kong", "hello")])
        self.assertEqual(rt.store.rides, [True])

    def test_session_without_ride_attribute_does_not_ride(self):
        _, store, _ = self.say("Kong")
        self.assertEqual(store.rows, [("Kong", "kong", "hello")])
        self.assertEqual(store.rides, [False])

    def test_a_message_for_the_creator_is_recorded_once(self):
        team, store, inbox = self.say("creator")
        self.assertEqual(store.rows, [("creator", "codeteam", "hello")])
        self.assertEqual(team.logged, [("NOTE", "creator", "hello")])
        self.assertEqual(len(inbox), 1)

    def test_the_creator_and_a_session_get_one_record_each(self):
        team, store, inbox = self.say("creator,Kong")
        self.assertEqual(store.rows, [("creator", "codeteam", "hello"), ("creator,Kong", "kong", "hello")])
        self.assertEqual(len(inbox), 1)

    def test_an_answer_to_codeteam_itself_is_still_recorded_once(self):
        # An answer to a patrol line is not the creator's mail: recorded for no session, as before.
        team, store, inbox = self.say("codeteam", kind="ANSWER", text="idle: nothing open")
        self.assertEqual(store.rows, [("codeteam", "codeteam", "idle: nothing open")])
        self.assertEqual(store.marks[-1][2], "for codeteam; no session")
        self.assertEqual(inbox, [])

    def test_an_answer_to_the_creator_reaches_its_inbox(self):
        # D496: 35 ANSWERs addressed to `creator` were dropped as patrol replies because they did not name the creator.
        team, store, inbox = self.say("creator", kind="ANSWER", text="#4371: confirmed")
        self.assertEqual(store.rows, [("creator", "codeteam", "#4371: confirmed")])
        self.assertEqual(len(inbox), 1)

    def test_a_name_that_would_reach_no_one_is_refused_and_nothing_is_recorded(self):
        # D496: from the orchestrator, a name no session has fell back to the orchestrator itself and was dropped.
        with self.assertRaises(SystemExit) as refused:
            self.say("Orc-Codeteam-jj", kind="DONE", text="#4387 is live")
        self.assertIn("no session named Orc-Codeteam-jj", str(refused.exception.code))
        self.assertIn("nothing was sent", str(refused.exception.code))

    def test_a_refused_name_in_a_list_stops_the_whole_message(self):
        team, rt = FakeTeam(), SimpleNamespace(store=FakeStore(), herdr=SimpleNamespace(notify=lambda *a: None))
        with self.assertRaises(SystemExit):
            cli.cmd_say(team, rt, SimpleNamespace(type="NOTE", text=["x"], channel="general", sender="Orc-Codeteam",
                                                  to="Kong,Orc-Codeteam-jj"))
        self.assertEqual((rt.store.rows, team.logged), ([], []))

    def test_an_unknown_name_from_another_session_still_goes_to_the_orchestrator(self):
        team, store, inbox = self.say("Orc-Codeteam-jj", sender="Kong")
        self.assertEqual(store.rows, [("Orc-Codeteam-jj", "orc", "hello")])


if __name__ == "__main__":
    unittest.main()
