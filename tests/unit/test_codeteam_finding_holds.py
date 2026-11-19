"""finding_holds (share/codeteam_finding_holds.py; rule 12, D552): a security finding holds nothing, every other kind
holds as before."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_finding_holds import finding_holds  # noqa: E402


def test_a_security_finding_holds_nothing():
    assert finding_holds({"id": "f#1", "kind": "security", "severity": 1}) is False


def test_every_other_kind_holds():
    for kind in ("spec", "architecture", "boundary", "layer", "test", "comment", "other"):
        assert finding_holds({"id": "f#1", "kind": kind}) is True, kind


def test_a_finding_with_no_kind_holds():
    # Older records and test-failure findings carry no kind of their own here: they keep holding.
    assert finding_holds({"id": "f#1"}) is True
