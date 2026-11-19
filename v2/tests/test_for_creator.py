"""`for_creator` takes mail meant for codeteam's builder (the creator) into its inbox and leaves the patrol's answers
and codeteam's own messages out. A unit test (rule 11): for_creator's only other dependency is its inbox, a file in a
temp folder."""
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2 import cli  # noqa: E402


def test_mail_for_the_creator_reaches_its_inbox():
    with tempfile.TemporaryDirectory() as d, patch.object(cli, "CREATOR_INBOX", Path(d) / "creator-inbox.log"):
        a = SimpleNamespace(sender="Orc-Codeteam")
        assert cli.for_creator(a, "NOTE", "codeteam", "a gap in your fix"), "a NOTE to codeteam is for the creator"
        assert not cli.for_creator(a, "ANSWER", "codeteam", "BRANCHES: all mirrored"), \
            "a patrol ANSWER to codeteam is not"
        assert cli.for_creator(SimpleNamespace(sender="Designer-Codeteam"), "ANSWER", "codeteam",
                               "#1878: one still bites"), "a designer's ANSWER to codeteam is"
        assert not cli.for_creator(SimpleNamespace(sender="codeteam"), "NOTE", "codeteam", "x"), \
            "codeteam's own messages are not"
        assert len(cli.CREATOR_INBOX.read_text().splitlines()) == 2, "the inbox holds the two"


def test_an_answer_addressed_to_the_creator_is_the_creators():
    # D496: the patrol-reply exception is for ANSWERs to `codeteam`; one to `creator` is the creator's mail.
    with tempfile.TemporaryDirectory() as d, patch.object(cli, "CREATOR_INBOX", Path(d) / "creator-inbox.log"):
        a = SimpleNamespace(sender="Orc-Codeteam")
        assert cli.for_creator(a, "ANSWER", "creator", "#4371: confirmed"), "an ANSWER to creator is for the creator"
        assert cli.for_creator(a, "ANSWER", "Creator", "#4299, since 08:30"), "whatever the name's case"
        assert not cli.for_creator(a, "ANSWER", "codeteam", "#4371: confirmed"), "an ANSWER to codeteam is still not"
        assert len(cli.CREATOR_INBOX.read_text().splitlines()) == 2, "the inbox holds the two"
