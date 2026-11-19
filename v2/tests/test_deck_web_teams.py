"""The browser build panel's per-team runner counts."""
import unittest

from test_deck_web_page import Elements, call_js, classes, integration_only, needs_node


@integration_only
@needs_node
class TeamslotWebTests(unittest.TestCase):
    def test_teamslot_web_row_is_after_runner_and_busiest_first(self):
        runner = {"state": "live", "used": 3, "budget": 8, "swap": 0,
                  "teams": {"zeta": {"running": 1, "waiting": 2},
                            "widgets": {"running": 1, "waiting": 0},
                            "acme": {"running": 8, "waiting": 3},
                            "alpha": {"running": 1, "waiting": 2}}}
        markup = call_js("builds.js", "builds", {"queue": {"runner": runner}}, False, 600)
        rows = sorted((el for el in Elements(markup).found if "row" in classes(el)), key=lambda el: el["start"])
        texts = [row["text"] for row in rows]
        runner_index = next(i for i, text in enumerate(texts) if "budget" in text)
        self.assertEqual(texts[runner_index + 1],
                         "teams acme 8 run 3 wait alpha 1 run 2 wait zeta 1 run 2 wait widgets 1 run 0 wait")

    def test_teamslot_web_omits_row_without_teams(self):
        markup = call_js("builds.js", "builds", {"queue": {"runner": {"state": "live"}}}, False, 600)
        text = Elements(markup).found[-1]["text"]
        self.assertIn("budget", text)
        self.assertNotIn("teams", text)

    def test_teamslot_web_omits_row_for_empty_teams(self):
        markup = call_js("builds.js", "builds", {"queue": {"runner": {"state": "live", "teams": {}}}}, False, 600)
        text = Elements(markup).found[-1]["text"]
        self.assertIn("budget", text)
        self.assertNotIn("teams", text)

    def test_teamslot_web_omits_row_for_nonlive_runner(self):
        for state in ("stale", "none", "?"):
            with self.subTest(state=state):
                runner = {"state": state, "teams": {"acme": {"running": 8, "waiting": 3}}}
                builds = {"queue": {"runner": runner}, "warms": [{"state": "held"}]}
                markup = call_js("builds.js", "builds", builds, False, 600)
                text = Elements(markup).found[-1]["text"]
                self.assertIn("no live runner", text)
                self.assertNotIn("teams", text)
                self.assertNotIn("acme", text)
