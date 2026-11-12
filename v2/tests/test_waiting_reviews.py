"""Patrol tells the orchestrator about a Stage 3 review pending over 2 hours, once."""
import datetime as dt
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2 import patrol  # noqa: E402


class WaitingReviewsTest(unittest.TestCase):
    def setUp(self):
        self.land = Path(tempfile.mkdtemp()) / "land"
        (self.land / "reviews").mkdir(parents=True)
        self.now = time.time()

    def review(self, wo, age_h, state="pending", reviewers=None, stage=3):
        asked = dt.datetime.fromtimestamp(self.now - age_h * 3600).astimezone().isoformat(timespec="seconds")
        row = {"stage": stage, "wo": wo, "zone": "eventlog", "reviewers": reviewers or {"Kong": "pending"},
               "requested": asked, "state": state}
        (self.land / "reviews" / f"{wo}.json").write_text(json.dumps(row))

    def lines(self):
        return patrol.waiting_reviews(self.land, self.now)

    def test_a_review_pending_over_two_hours_is_reported(self):
        self.review("rework", 3)
        out = self.lines()
        self.assertEqual(len(out), 1)
        self.assertIn("eventlog: REVIEW WAITING rework, asked of Kong", out[0])
        self.assertTrue(any(w in out[0] for w in patrol.WAKES))

    def test_a_recent_review_is_not(self):
        self.review("fresh", 1)
        self.assertEqual(self.lines(), [])

    def test_an_answered_review_is_not(self):
        self.review("done", 5, state="land", reviewers={"Kong": "pass"})
        self.assertEqual(self.lines(), [])

    def test_only_the_reviewers_still_pending_are_named(self):
        self.review("two", 3, reviewers={"Kong": "pass", "Perkins": "pending"})
        out = self.lines()
        self.assertIn("asked of Perkins at", out[0])
        self.assertNotIn("Kong", out[0])

    def test_backlog_reviews_are_not_stage_3(self):
        self.review("backlog-x", 9, stage=None)
        self.assertEqual(self.lines(), [])

    def test_the_line_is_the_same_on_the_next_patrol(self):
        self.review("rework", 3)
        first = self.lines()
        self.now += 600
        self.assertEqual(self.lines(), first)


if __name__ == "__main__":
    unittest.main()
