#!/usr/bin/env python3
"""reported_repeat picks the follow-up whose landed report already covers a new slow-tests flag (the slow-test rule;
WidgetCoreKit's slow#5, #6 and #7 were one cause). A unit test: plain lists and ISO times."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_slow_repeat import REPEAT_HOURS, reported_repeat  # noqa: E402

STEP = "tests WidgetCoreKit (packages/kits/WidgetCoreKit)"


def item(ident, closed, *, zone="WidgetCoreKit", step=STEP, state="closed", closed_by="amk-report"):
    return {"id": ident, "zone": zone, "steps": [{"step": step, "run_s": 262.0}], "state": state,
            "closed": closed, "closed_by": closed_by}


class ReportedRepeatTests(unittest.TestCase):
    def test_a_report_landed_within_the_window_on_the_same_zone_and_step_covers_the_flag(self):
        slow5 = item("slow#5", "2026-11-15T01:07:00-06:00")
        self.assertIs(reported_repeat([slow5], "WidgetCoreKit", STEP, "2026-11-15T02:00:00-06:00"), slow5)

    def test_the_window_is_24_hours(self):
        self.assertEqual(REPEAT_HOURS, 24)
        slow5 = item("slow#5", "2026-11-14T02:00:00-06:00")
        self.assertIs(reported_repeat([slow5], "WidgetCoreKit", STEP, "2026-11-15T02:00:00-06:00"), slow5)
        self.assertIsNone(reported_repeat([slow5], "WidgetCoreKit", STEP, "2026-11-15T02:00:01-06:00"))

    def test_the_newest_matching_report_is_the_one(self):
        older, newer = item("slow#5", "2026-11-15T01:07:00-06:00"), item("slow#6", "2026-11-15T02:12:00-06:00")
        self.assertIs(reported_repeat([newer, older], "WidgetCoreKit", STEP, "2026-11-15T02:28:00-06:00"), newer)

    def test_another_zone_another_slowest_step_a_drop_or_an_open_one_does_not_cover_it(self):
        when = "2026-11-15T02:00:00-06:00"
        for other in (item("slow#2", "2026-11-15T01:00:00-06:00", zone="WidgetStoreKit"),
                      item("slow#3", "2026-11-15T01:00:00-06:00", step="tests AcmeX-App (apps/AcmeX-App)"),
                      item("slow#4", "2026-11-15T01:00:00-06:00", state="dropped", closed_by=None),
                      item("slow#5", None, state="open", closed_by=None)):
            self.assertIsNone(reported_repeat([other], "WidgetCoreKit", STEP, when), other["id"])

    def test_a_report_closed_after_the_flag_or_unreadable_times_cover_nothing(self):
        later = item("slow#5", "2026-11-15T03:00:00-06:00")
        self.assertIsNone(reported_repeat([later], "WidgetCoreKit", STEP, "2026-11-15T02:00:00-06:00"))
        self.assertIsNone(reported_repeat([later], "WidgetCoreKit", STEP, "NOW"))
        self.assertIsNone(reported_repeat([item("slow#5", "soon")], "WidgetCoreKit", STEP, "2026-11-15T02:00:00-06:00"))
        self.assertIsNone(reported_repeat([item("slow#5", "2026-11-15T01:00:00")], "WidgetCoreKit", STEP,
                                          "2026-11-15T02:00:00-06:00"), "a naive time beside an aware one")


if __name__ == "__main__":
    result = unittest.main(exit=False).result
    sys.exit(0 if result.wasSuccessful() else 1)
