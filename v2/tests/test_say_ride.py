"""Say's ride-along flag through the parser, store and scheduler (ZIT)."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import integration_only  # noqa: E402
from codeteam2 import cli  # noqa: E402
from codeteam2.scheduler import Runtime  # noqa: E402
from codeteam2.store import Store  # noqa: E402
from test_v2 import FakeHerdr, FakeTeam  # noqa: E402


@integration_only
class SayRideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.team = FakeTeam(self.tmp.name, ["a"])
        self.team.t.assistants = {}
        self.team.t.managed = lambda _: False
        self.team.is_user = lambda _: False
        self.team.resolve_recipient = lambda name, channel: self.team.session(name)
        self.team.mirror_to_channel_log = lambda *args: None
        self.herdr = FakeHerdr({"a": "idle"})
        self.store = Store(Path(self.tmp.name) / "messages.db")
        self.addCleanup(self.store.db.close)
        self.rt = Runtime(self.team, log=lambda *_: None, herdr=self.herdr, store=self.store)
        self.rt.workspace = lambda create=True: "w1"

    def say_ride(self):
        cli.cmd_say(self.team, self.rt, SimpleNamespace(channel="general", sender="codeteam", type="NOTE",
                                                        to="Coord-a", text=["ride note"], ride=True))

    def parse_say(self, args):
        with patch.object(cli, "Team", return_value=self.team), patch.object(cli, "Runtime", return_value=self.rt), \
             patch.object(cli, "cmd_say") as say:
            cli.main(["say", str(Path(self.tmp.name) / "team.toml"), *args])
        return say.call_args.args[2]

    def test_parser_accepts_ride_before_positionals(self):
        args = self.parse_say(["--ride", "general", "codeteam", "NOTE", "Coord-a", "text"])
        self.assertIs(args.ride, True)
        self.assertEqual((args.channel, args.sender, args.type, args.to, args.text),
                         ("general", "codeteam", "NOTE", "Coord-a", ["text"]))

    def test_parser_accepts_ride_after_positionals(self):
        args = self.parse_say(["general", "codeteam", "NOTE", "Coord-a", "text", "--ride"])
        self.assertIs(args.ride, True)
        self.assertEqual(args.text, ["text"])

    def test_parser_defaults_to_not_ride(self):
        args = self.parse_say(["general", "codeteam", "NOTE", "Coord-a", "text"])
        self.assertIs(args.ride, False)

    def test_say_stores_ride_for_the_session(self):
        self.say_ride()
        rows = self.store.pending("a")
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["body"], rows[0]["ride"]), ("ride note", 1))

    def test_say_ride_waits_for_real_mail_before_prompting(self):
        self.say_ride()
        self.rt.tick()
        self.assertEqual(self.herdr.prompts, [])
        self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "real work")
        self.rt.tick()
        self.assertEqual(len(self.herdr.prompts), 1)
        text = self.herdr.prompts[0][1]
        self.assertLess(text.index("real work"), text.index("ride note"))

    def test_stored_ride_does_not_start_absent_session(self):
        self.herdr.status["a"] = "absent"
        ride = self.store.add("general", "codeteam", "NOTE", "Coord-a", "a", "ride note", ride=True)
        self.rt.tick()
        self.assertIsNone(self.team.launched)
        self.assertEqual(self.herdr.runs, [])
        self.assertEqual(self.store.get(ride)["state"], "queued")
        real = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "real work")
        self.rt.tick()
        self.assertEqual(self.team.launched[0], "a")
        text = self.team.launched[1]
        self.assertIn("real work", text)
        self.assertIn("ride note", text)
        self.assertEqual([self.store.get(mid)["state"] for mid in (ride, real)], ["delivered", "delivered"])

    def test_stored_ride_does_not_prompt_idle_session(self):
        ride = self.store.add("general", "codeteam", "NOTE", "Coord-a", "a", "ride note", ride=True)
        self.rt.tick()
        self.assertEqual(self.herdr.prompts, [])
        self.assertEqual(self.store.get(ride)["state"], "queued")
        real = self.store.add("general", "Orc", "REQUEST", "Coord-a", "a", "real work")
        self.rt.tick()
        self.assertEqual(len(self.herdr.prompts), 1)
        text = self.herdr.prompts[0][1]
        self.assertLess(text.index("real work"), text.index("ride note"))
        self.assertEqual([self.store.get(mid)["state"] for mid in (ride, real)], ["delivered", "delivered"])
