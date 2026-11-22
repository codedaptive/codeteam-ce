import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_passing import PASSING


def test_passing_includes_no_tests():
    assert PASSING == ("PASS", "NO TESTS")
