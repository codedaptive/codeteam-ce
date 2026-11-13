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
        self.rows, self.marks = [], []

    def add(self, channel, sender, kind, to, recipient, text):
        self.rows.append((to, recipient, text))
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


if __name__ == "__main__":
    unittest.main()
