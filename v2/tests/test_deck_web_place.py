"""Placement and row heights for the browser deck's two-column layout."""
import json
import random
import subprocess
import unittest

from test_deck_web_page import BASE_UI, JS, NODE, call_js, integration_only, needs_node, snapshot


@integration_only
@needs_node
class PlaceTests(unittest.TestCase):
    def test_teams_outrun_details(self):
        self.assertEqual(call_js("place.js", "place", [5, 5, 5, 5, 5, 5], [3, 3]),
                         [[['t', 0], ['t', 1], ['t', 3], ['t', 5]],
                          [['d', 0], ['d', 1], ['t', 2], ['t', 4]]])

    def test_details_outrun_teams(self):
        self.assertEqual(call_js("place.js", "place", [4], [3, 3, 3, 3]),
                         [[['t', 0], ['d', 2]], [['d', 0], ['d', 1], ['d', 3]]])

    def test_both_columns_same_height(self):
        self.assertEqual(call_js("place.js", "place", [3, 3], [2, 4]),
                         [[['t', 0], ['t', 1]], [['d', 0], ['d', 1]]])

    def test_no_teams(self):
        self.assertEqual(call_js("place.js", "place", [], [5, 2, 2, 4]),
                         [[['d', 0]], [['d', 1], ['d', 2], ['d', 3]]])

    def test_one_team(self):
        self.assertEqual(call_js("place.js", "place", [6], [4, 4, 4]),
                         [[['t', 0], ['d', 2]], [['d', 0], ['d', 1]]])

    def test_nothing(self):
        self.assertEqual(call_js("place.js", "place", [], []), [[], []])

    def test_no_details(self):
        self.assertEqual(call_js("place.js", "place", [2, 2, 2], []),
                         [[['t', 0], ['t', 2]], [['t', 1]]])

    def test_each_index_once_and_in_column_order(self):
        rng = random.Random(467)
        for _ in range(40):
            teams = [rng.randint(1, 9) for _ in range(rng.randrange(7))]
            details = [rng.randint(1, 9) for _ in range(rng.randrange(7))]
            with self.subTest(teams=teams, details=details):
                columns = call_js("place.js", "place", teams, details)
                self.assertEqual(len(columns), 2)
                placed = [tuple(box) for column in columns for box in column]
                expected = ([('t', i) for i in range(len(teams))]
                            + [('d', i) for i in range(len(details))])
                self.assertCountEqual(placed, expected)
                for column in columns:
                    for kind in ('t', 'd'):
                        indices = [index for label, index in column if label == kind]
                        self.assertEqual(indices, sorted(indices))

    def test_input_arrays_are_not_mutated(self):
        script = (f"import {{ place }} from {json.dumps((JS / 'place.js').as_uri())};\n"
                  "const teams = [5, 5, 5, 5, 5, 5], details = [3, 3];\n"
                  "place(teams, details);\n"
                  "process.stdout.write(JSON.stringify([teams, details]));\n")
        done = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), [[5, 5, 5, 5, 5, 5], [3, 3]])


@integration_only
@needs_node
class RowsOfTests(unittest.TestCase):
    def test_split_counts_taller_column_not_both_columns(self):
        markup = ('<section class="box"><div class="split" data-rows="8">'
                  '<div class="split-l">' + '<div class="row">left</div>' * 8 + '</div>'
                  '<div class="split-r">' + '<div class="row">right</div>' * 8 + '</div>'
                  '</div></section>')
        self.assertEqual(call_js("rowsOf.js", "rowsOf", markup), 9.5)

    def test_row_outside_split_still_counts(self):
        markup = ('<section class="box"><div class="split" data-rows="8">'
                  '<div class="split-l">' + '<div class="row">left</div>' * 8 + '</div>'
                  '<div class="split-r">' + '<div class="row">right</div>' * 8 + '</div>'
                  '</div><div class="row">outside</div></section>')
        self.assertEqual(call_js("rowsOf.js", "rowsOf", markup), 10.5)

    def test_empty_markup(self):
        self.assertEqual(call_js("rowsOf.js", "rowsOf", ""), 0)

    def test_box_with_three_rows(self):
        markup = ('<section class="box k-edge x" data-panel="x"><header>Title</header><div class="body">'
                  '<div class="row " title="a">a</div><div class="row wrap" title="b">b</div>'
                  '<div class="row " title="c">c</div></div></section>')
        self.assertEqual(call_js("rowsOf.js", "rowsOf", markup), 4.5)

    def test_agents_without_box_edge(self):
        markup = ('<section class="agents" data-panel="agents">'
                  '<div class="srow current">a</div><div class="mrow">b</div></section>')
        self.assertEqual(call_js("rowsOf.js", "rowsOf", markup), 2)

    def test_alpha_team_box(self):
        snap = snapshot()
        markup = call_js("teamBox.js", "teamBox", snap["teams"][0], snap["at"], "alpha/orc", [], BASE_UI["motion"])
        self.assertEqual(call_js("rowsOf.js", "rowsOf", markup), 5.5)
