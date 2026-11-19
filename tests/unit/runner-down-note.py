#!/usr/bin/env python3
"""runner_down_note says what launchd says about a runner that is down. A unit test: the
input is `launchctl print` text."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_runner_down import runner_down_note  # noqa: E402

CRASHING = """gui/501/com.codeteam.codeteam-land.other-checkout = {
\tactive count = 0
\tstate = spawn scheduled
\tendpoints = {
\t\t"x" = {
\t\t\tstate = active
\t\t}
\t}
\truns = 412
\tlast exit code = 1
}
"""
WAITING = "gui/501/com.codeteam.codeteam-recheck.demo = {\n\tstate = waiting\n\tlast exit code = 0\n}\n"
ROOT, MANIFEST = Path("/x/team-other-checkout"), Path("/x/jj/teams/other-checkout.toml")


class RunnerDownNoteTests(unittest.TestCase):
    def test_a_runner_that_exits_at_start_says_so_with_launchds_state_and_exit_code(self):
        note = runner_down_note("landing queue runner not running", CRASHING, ROOT, MANIFEST)
        self.assertTrue(note.startswith("watchdog: landing queue runner not running (launchd: spawn scheduled, "
                                        "last exit code 1, so it exits at start"), note)
        self.assertIn("/x/team-other-checkout/land/queue-run.log", note)
        self.assertIn("codeteam-land /x/jj/teams/other-checkout.toml service install", note)

    def test_the_jobs_own_state_is_read_not_a_nested_one(self):
        self.assertNotIn("active", runner_down_note("landing queue runner not running", CRASHING, ROOT, MANIFEST))

    def test_a_clean_last_exit_is_not_called_a_failure(self):
        note = runner_down_note("recheck runner not running", WAITING, ROOT, MANIFEST)
        self.assertIn("(launchd: waiting)", note)
        self.assertNotIn("exit code", note)
        self.assertIn("/x/team-other-checkout/land/recheck-run.log", note)

    def test_no_launchd_answer_still_names_the_log_and_the_fix(self):
        note = runner_down_note("validation runner not running", "", ROOT, MANIFEST)
        self.assertEqual(note, "watchdog: validation runner not running. Its log is "
                               "/x/team-other-checkout/land/validate-run.log. Once the cause is gone, "
                               "`codeteam-land /x/jj/teams/other-checkout.toml service install` starts the runners again.")


if __name__ == "__main__":
    result = unittest.main(exit=False).result
    sys.exit(0 if result.wasSuccessful() else 1)
