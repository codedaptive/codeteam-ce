"""Misaddressed session answers are refused before any recipient gets mail."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conftest import integration_only  # noqa: E402
from codeteam2 import cli  # noqa: E402
from test_say import FakeStore, FakeTeam, KONG  # noqa: E402


class SayRefusalTests(unittest.TestCase):
    def setUp(self):
        self.team = FakeTeam()
        self.team.product = "acme"
        self.team.t.orc_name = lambda: "Orc-Acme"
        self.rt = SimpleNamespace(store=FakeStore(), herdr=SimpleNamespace(notify=lambda *a: None))
        self.args = SimpleNamespace(type="ANSWER", text=["review blocked"], channel="general", sender="Kong",
                                    to="codeteam")
        self.other = patch.object(cli, "other_team", return_value=None)
        self.other.start()
        self.addCleanup(self.other.stop)

    def refusal(self):
        with self.assertRaises(SystemExit) as refused:
            cli.cmd_say(self.team, self.rt, self.args)
        self.assertNotEqual(refused.exception.code, 0)
        self.assertEqual((self.rt.store.rows, self.team.logged), ([], []))
        return str(refused.exception.code)

    def test_answer_is_refused_with_orchestrator_request_guidance(self):
        text = self.refusal()
        self.assertIn("Orc-Acme", text)
        self.assertIn("REQUEST", text)
        self.assertNotIn("ANSWER Orc-Acme", text)
        self.assertIn("result", text.lower())

    def test_product_refusal_explains_forwarded_codeteam_request(self):
        self.assertIn("REQUEST codeteam", self.refusal())

    def test_codeteam_refusal_does_not_offer_forwarding_to_itself(self):
        self.team.product = "codeteam"
        self.team.t.orc_name = lambda: "Orc-Codeteam"
        text = self.refusal()
        self.assertNotIn("REQUEST codeteam", text)
        self.assertIn("reply", text.lower())

    def orchestrator_sends(self, orc):
        self.team.t.orc_name = lambda: orc
        self.team.session = lambda name: SimpleNamespace(key="orc", display=orc) if name == orc else None
        self.args.sender = orc
        return self.refusal()

    def test_product_orchestrator_is_not_told_to_request_itself(self):
        text = self.orchestrator_sends("Orc-Acme")
        self.assertNotIn("REQUEST Orc-Acme", text)
        self.assertIn("REQUEST codeteam", text)
        self.assertIn("reads no reply", text)

    def test_codeteam_orchestrator_gets_no_request_line(self):
        self.team.product = "codeteam"
        text = self.orchestrator_sends("Orc-Codeteam")
        self.assertNotIn("REQUEST Orc-Codeteam", text)
        self.assertNotIn("REQUEST codeteam", text)
        self.assertIn("reads no reply", text)

    def test_codeteam_and_another_recipient_are_refused_whole(self):
        self.args.to = "codeteam,Orc-Acme"
        text = self.refusal().lower()
        self.assertIn("resend", text)
        self.assertIn("without", text)
        self.assertIn("codeteam", text)

    def test_product_request_is_forwarded(self):
        self.args.type = "REQUEST"
        with patch.object(cli, "other_team", return_value=Path("teams/codeteam.toml")), \
             patch.object(cli, "forward") as forward:
            cli.cmd_say(self.team, self.rt, self.args)
        self.assertEqual(forward.call_count, 1)
        self.assertEqual(forward.call_args.args[3:5], ("REQUEST", "codeteam"))
        self.assertEqual(self.rt.store.rows, [])

    @integration_only
    def test_designer_answer_goes_to_creator_inbox(self):
        self.args.sender = "Designer-Acme"
        self.team.session = lambda name: KONG if name == "Designer-Acme" else None
        with tempfile.TemporaryDirectory() as d, patch.object(cli, "CREATOR_INBOX", Path(d) / "inbox"):
            cli.cmd_say(self.team, self.rt, self.args)
            self.assertIn("Designer-Acme | ANSWER | review blocked", cli.CREATOR_INBOX.read_text())
        self.assertEqual(self.rt.store.rows, [("codeteam", "codeteam", "review blocked")])

    @integration_only
    def test_answer_mentioning_creator_goes_to_creator_inbox(self):
        self.args.text = ["creator, please look"]
        with tempfile.TemporaryDirectory() as d, patch.object(cli, "CREATOR_INBOX", Path(d) / "inbox"):
            cli.cmd_say(self.team, self.rt, self.args)
            self.assertIn("Kong | ANSWER | creator, please look", cli.CREATOR_INBOX.read_text())
        self.assertEqual(self.rt.store.rows, [("codeteam", "codeteam", "creator, please look")])

    def test_tool_sender_is_not_refused(self):
        self.args.sender = "codeteam"
        cli.cmd_say(self.team, self.rt, self.args)
        self.assertEqual(self.rt.store.rows, [("codeteam", "codeteam", "review blocked")])

    def test_unknown_name_keeps_exact_refusal(self):
        self.args.sender = "Orc-Codeteam"
        self.args.to = "No-Such-Session"
        text = self.refusal()
        self.assertEqual(text, 'codeteam2 say: no session named No-Such-Session in team acme, so this would reach '
                               'no one; nothing was sent. For a session of another team, give that team\'s manifest: '
                               'codeteam2 say <its manifest> general Orc-Codeteam ANSWER <name> "<text>"')
