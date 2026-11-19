"""build_shown (work order teamslot, decision 7): whether the deck's BUILDS box shows. Unit tests: the pure
function only."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2.deck.build_shown import build_shown  # noqa: E402

JOB = {"team": "acme"}


class BuildShownTests(unittest.TestCase):
    def test_nothing_at_all_shows_nothing(self):
        self.assertFalse(build_shown([], [], [], {}, []))

    def test_a_runner_that_is_not_live_shows_nothing_on_its_own(self):
        for state in ("stale", "none", "?"):
            with self.subTest(state=state):
                self.assertFalse(build_shown([], [], [], {"state": state}, []))

    def test_each_reason_alone_shows_the_box(self):
        cases = {"running": ([JOB], [], [], {}, []), "queued": ([], [JOB], [], {}, []),
                 "waits": ([], [], [[("waits", "dim")]], {}, []), "live": ([], [], [], {"state": "live"}, []),
                 "warms": ([], [], [], {}, [{"state": "running"}])}
        for reason, args in cases.items():
            with self.subTest(reason=reason):
                self.assertIs(build_shown(*args), True)


if __name__ == "__main__":
    unittest.main()
