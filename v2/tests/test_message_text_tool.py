"""Tool-sent mail tells its recipient how to request a ruling."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2.scheduler import Runtime  # noqa: E402
from codeteam2.store import RUNTIME  # noqa: E402
from codeteam2.team import CODETEAM2  # noqa: E402


class MessageTextToolTests(unittest.TestCase):
    def setUp(self):
        self.rt = Runtime.__new__(Runtime)
        self.rt.team = SimpleNamespace(t=SimpleNamespace(manifest="teams/acme.toml", orc_name=lambda: "Orc-Acme"))
        self.lane = SimpleNamespace(key="lane", display="Coord-lane")
        self.orc = SimpleNamespace(key="orc", display="Orc-Acme")

    def message(self, sender, kind="REQUEST", body="Review work order wo-1"):
        return {"id": 1, "kind": kind, "sender": sender, "recipient": "Coord-lane", "body": body}

    def test_tool_bundle_directs_questions_to_orchestrator(self):
        text = self.rt.message_text(self.lane, [self.message("codeteam"), self.message("codeteam", "NOTE")])
        closing = text.rsplit("\n", 1)[-1]
        self.assertNotIn("ANSWER codeteam", closing)
        self.assertIn("Orc-Acme", closing)
        self.assertIn("REQUEST", closing)
        self.assertIn("work order", closing.lower())
        self.assertIn("reply", closing.lower())
        self.assertIn("codeteam2 say", closing)

    def test_tool_mail_to_orchestrator_does_not_request_itself(self):
        text = self.rt.message_text(self.orc, [self.message("codeteam")])
        closing = text.rsplit("\n", 1)[-1]
        self.assertNotIn("ANSWER codeteam", closing)
        self.assertNotIn("REQUEST Orc-Acme", closing)
        self.assertIn("reply", closing.lower())

    def test_mixed_senders_keep_exact_reply_line(self):
        text = self.rt.message_text(self.lane, [self.message("codeteam"), self.message("Kong")])
        self.assertTrue(text.endswith(f'\n(Reply or report with: {CODETEAM2} say teams/acme.toml general Coord-lane ANSWER <to> "<text>")'))

    def test_single_other_sender_keeps_exact_reply_line(self):
        text = self.rt.message_text(self.lane, self.message("Kong"))
        self.assertTrue(text.endswith(f'\n(Reply or report with: {CODETEAM2} say teams/acme.toml general Coord-lane ANSWER Kong "<text>")'))

    def test_runtime_is_unchanged(self):
        self.assertEqual(self.rt.message_text(self.lane, self.message("codeteam", RUNTIME, "/compact")), "/compact")
