"""The deck's browser page (v2/codeteam2/deck/web): its ES modules run under node, and the real web folder served
by build_server. Every case needs node or a socket, so every class is integration and skips without
node. Expected facts are copied by hand from v2/tests/deck_golden_120.txt, the terminal screen of the same
fixture (test_deck.render_snapshot) at 120 columns."""
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from conftest import integration_only

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import test_deck  # noqa: E402

WEB = Path(__file__).resolve().parent.parent / "codeteam2" / "deck" / "web"
JS = WEB / "js"
NODE = shutil.which("node")
needs_node = unittest.skipUnless(NODE, "node is not installed")
# Box-drawing and block characters the terminal draws with; the page draws bars and boxes with CSS or SVG.
TERMINAL_GLYPHS = "╭╮╰╯│─▰▱▮▯█▁▂▃▄▅▆▇▏▎▍▌▋▊▉"
BASE_UI = {"cursor": 0, "expanded": [], "allAgents": False, "teamAgents": False, "teamFilter": None, "flash": [],
           "motion": False}


def call_js(module, export, *args):
    """export(*args) from web/js/<module>, run by node with the arguments passed as JSON on stdin; its JSON result."""
    script = (f"import {{ {export} }} from {json.dumps((JS / module).as_uri())};\n"
              "let input = '';\n"
              "process.stdin.setEncoding('utf8');\n"
              "process.stdin.on('data', (chunk) => { input += chunk; });\n"
              f"process.stdin.on('end', () => {{ process.stdout.write(JSON.stringify({export}(...JSON.parse(input)))); }});\n")
    done = subprocess.run([NODE, "--input-type=module", "-e", script], input=json.dumps(list(args)),
                          capture_output=True, text=True, timeout=60)
    if done.returncode:
        raise AssertionError(f"node failed on {module}.{export}:\n{done.stderr}")
    return json.loads(done.stdout)


def snapshot():
    """The golden fixture as the page receives it: through JSON, as /snapshot.json serves it."""
    return json.loads(json.dumps(test_deck.render_snapshot()))


@integration_only
@needs_node
class ModuleTests(unittest.TestCase):
    def test_every_module_passes_node_check(self):
        files = sorted(JS.glob("*.js"))
        for name in ("main.js", "deck.js", "keys.js", "visible.js"):
            self.assertIn(JS / name, files)
        for path in files:
            with self.subTest(path.name):
                done = subprocess.run([NODE, "--check", str(path)], capture_output=True, text=True, timeout=60)
                self.assertEqual(done.returncode, 0, done.stderr)


class Elements(HTMLParser):
    """Every element of a markup string as {tag, attrs, start, markup, text}; text has each tag as a space,
    entities unescaped and whitespace collapsed."""
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    def __init__(self, markup):
        super().__init__(convert_charrefs=True)
        self.markup, self.found, self.open = markup, [], []
        self.lines = [0] + [i + 1 for i, c in enumerate(markup) if c == "\n"]
        self.feed(markup)
        self.close()

    def _at(self):
        line, col = self.getpos()
        return self.lines[line - 1] + col

    def handle_starttag(self, tag, attrs):
        for el in self.open:
            el["text"].append(" ")
        if tag not in self.VOID:
            self.open.append({"tag": tag, "attrs": dict(attrs), "start": self._at(), "text": []})

    def handle_endtag(self, tag):
        while self.open:
            el = self.open.pop()
            el["markup"] = self.markup[el["start"]:self._at() + len(f"</{tag}>")]
            el["text"] = " ".join("".join(el["text"]).split())
            self.found.append(el)
            if el["tag"] == tag:
                break
        for el in self.open:
            el["text"].append(" ")

    def handle_data(self, data):
        for el in self.open:
            el["text"].append(data)


def classes(el):
    return (el["attrs"].get("class") or "").split()


class DeckCase(unittest.TestCase):
    """Helpers over one renderDeck page: its panels by data-panel, rows by their text, session rows by data-id."""

    def render(self, snap=None, **ui):
        markup = call_js("deck.js", "renderDeck", snap or snapshot(), {**BASE_UI, **ui})
        return markup, Elements(markup).found

    def panel(self, els, name):
        hits = [el for el in els if el["attrs"].get("data-panel") == name]
        self.assertTrue(hits, f"no data-panel={name!r}")
        return hits[0]

    def inside(self, els, outer):
        end = outer["start"] + len(outer["markup"])
        return [el for el in els if outer["start"] <= el["start"] < end]

    def row_with(self, els, outer, text):
        """The smallest row element in outer whose text holds text."""
        rows = [el for el in self.inside(els, outer) if "row" in classes(el) and text in el["text"]]
        self.assertTrue(rows, f"no row with {text!r} in {outer['text']!r}")
        return min(rows, key=lambda el: len(el["markup"]))

    def session(self, els, sid):
        hits = [el for el in els if el["attrs"].get("data-id") == sid]
        self.assertEqual(len(hits), 1, sid)
        return hits[0]

    def assertFacts(self, el, *facts):
        """Each fact appears in el's text as a whole token: no letter or digit right before or after it, so
        "1 running" does not pass on "11 running"."""
        for fact in facts:
            with self.subTest(fact):
                self.assertRegex(el["text"], rf"(?<![0-9A-Za-z]){re.escape(fact)}(?![0-9A-Za-z])")


@integration_only
@needs_node
class RenderDeckTests(DeckCase):
    """renderDeck over the golden fixture, cursor on Orc-Alpha, motion off. Each fact is looked for in its own panel."""

    @classmethod
    def setUpClass(cls):
        cls.markup = call_js("deck.js", "renderDeck", snapshot(), BASE_UI)
        cls.els = Elements(cls.markup).found

    def at(self, name):
        return self.panel(self.els, name)

    def test_header_counts_and_time(self):
        self.assertFacts(self.at("header"), "CODETEAM DECK", "1 UP", "2 HALTED", "1 LANES WORKING", "2 ALERTS", "15:00")

    def test_legend(self):
        self.assertFacts(self.at("legend"), "orc", "designer", "guard", "lane", "crew", "working", "between turns", "idle",
                         "done", "blocked")

    def test_fleet(self):
        fleet = self.at("fleet")
        self.assertFacts(fleet, "FLEET", "3 teams", "alpha", "beta", "gamma", "1/2", "down", "halted", "loop off", "7/h",
                         "300G free", "all beating")
        self.assertIn('class="pips"', fleet["markup"])

    def test_alpha_box(self):
        box = self.at("team:alpha")
        self.assertFacts(box, "3 sessions", "loop 5s", "1/2 lanes", "$9.60 today", "7/h", "Orc-Alpha", "Coord-a",
                         "Coord-b")
        self.assertIn('class="pips"', box["markup"])
        self.assertIn('<svg class="spark"', box["markup"])

    def test_session_rows(self):
        # (id, facts from the golden row, state glyph and its colour, name colour by role)
        for sid, facts, glyph, glyph_colour, role_colour in (
                ("alpha/orc", ("Orc-Alpha", "10m", "42%", "$3.20"), "◐", "c-sky", "c-coral"),
                ("alpha/a", ("Coord-a", "3m", "85%", "$3.20", "blocked"), "■", "c-salmon", "c-blue"),
                ("alpha/b", ("Coord-b", "1m", "60%", "$3.20", "typing"), "○", "c-dim", "c-blue"),
                ("beta/kong", ("Kong", "?", "$?"), "?", "c-amber", "c-teal")):
            with self.subTest(sid):
                el = self.session(self.els, sid)
                self.assertFacts(el, *facts)
                inner = self.inside(self.els, el)
                self.assertTrue(any(x["text"] == glyph and glyph_colour in classes(x) for x in inner), el["markup"])
                self.assertTrue(any(x["text"] == facts[0] and role_colour in classes(x) for x in inner), el["markup"])

    def test_orc_alpha_context_bar_is_42_percent(self):
        el = self.session(self.els, "alpha/orc")
        self.assertRegex(el["markup"], r'<span class="bar ctx"><i class="bg-orange" style="width:42\.00%">')

    def test_beta_down_box(self):
        self.assertFacts(self.at("team:beta"), "1 session", "down", "Kong", "$? today")

    def test_halted_rows(self):
        box = self.at("halted")
        self.assertFacts(self.row_with(self.els, box, "beta"), "down", "loop off never started")
        self.assertFacts(self.row_with(self.els, box, "gamma"), "halted", "loop off 2h14m", "3 waiting")

    def test_focus_on_orc_alpha(self):
        self.assertFacts(self.at("focus"), "Opus 5.5", "Orc-Alpha", "between", "10m", "high", "role orc", "alpha",
                         "42%", "420k/1.0M", "⟲2", "$3.20 session", "$10.10 seat today", "warm", "20m left",
                         "hit 90%", "tools read", "0 waiting", "↓4 today", "oldest –", "flags none")

    def test_builds(self):
        box = self.at("builds")
        self.assertFacts(box, "BUILDS", "6 jobs", "3 running", "3 queued", "3/6", "50%", "full 1/1", "post 0/2",
                         "pre 0/2", "dev 2/∞", "f-run", "10:00", "cost 4.0", "d-run2", "pid gone", "held warm", "d-q1",
                         "wait 3m", "waits 24h", "med 2m", "max 10m", "warm held 1m wt2")
        strip = re.search(r'<span class="strip">(.*?)</span>', box["markup"])
        self.assertEqual(re.findall(r'<i class="bg-(\w+)', strip.group(1)), ["green"] * 3 + ["faint"] * 3)

    def test_log(self):
        self.assertFacts(self.at("log"), "log", "alpha", "14:59:00", "Orc-Alpha", "Coord-a", "REQUEST", "Stranger",
                         "NOTE", "↓9", "held 2", "queued 2", "bcast 1", "from Orc-Alpha 5 Coord-a 3", "to Coord-a 4")

    def test_disk(self):
        self.assertFacts(self.at("disk"), "DISK", "gamma", "95.0G", "alpha", "80.0G", "wt 40.0G", "cargo-target 12.0G",
                         "wt2 6.0G", "target 2.0G", "beta", "not measured yet", "largest 12.0G cargo-target wt",
                         "300G free", "10m ago")

    def test_alerts_newest_first(self):
        box = self.at("alerts")
        self.assertFacts(box, "ALERTS", "newest first", "14:59", "build output 12.0 GB", "14:57",
                         "Coord-a blocked for 3 min")
        self.assertLess(box["text"].index("build output 12.0 GB"), box["text"].index("Coord-a blocked for 3 min"))

    def test_keys(self):
        self.assertFacts(self.at("keys"), "j k move", "expand", "a all agents", "t team agents", "f team filter",
                         "d disk now")

    def test_no_terminal_box_or_block_characters(self):
        self.assertEqual([c for c in TERMINAL_GLYPHS if c in self.markup], [])

    def test_agents_follow_the_cursor_without_all(self):
        # Orc-Alpha has no subagents, so render._agents shows no panel.
        self.assertEqual([el for el in self.els if el["attrs"].get("data-panel") == "agents"], [])

    def test_all_agents_shows_coord_a_subagents(self):
        _, els = self.render(allAgents=True)
        self.assertFacts(self.panel(els, "agents"), "1 running", "2 total", "all sessions", "baseline tests",
                         "port the parser", "Coord-a")

    def test_team_agents_show_the_cursor_teams_subagents_and_all_agents_every_teams(self):
        snap = snapshot()
        kong = next(s for t in snap["teams"] if t["name"] == "beta" for s in t["sessions"])
        kong["agents"] = [test_deck.render_agent("k1", description="guard the review", finished=True)]
        _, els = self.render(snap, teamAgents=True)
        team = self.panel(els, "agents")
        self.assertFacts(team, "1 running", "2 total", "team alpha", "baseline tests", "port the parser", "Coord-a")
        self.assertNotIn("guard the review", team["text"])
        _, els = self.render(snap, allAgents=True)
        self.assertFacts(self.panel(els, "agents"), "1 running", "3 total", "all sessions", "guard the review", "Kong")

    def test_names_are_escaped(self):
        snap = snapshot()
        snap["teams"][0]["sessions"][0]["name"] = "<b>x</b>"
        markup, _ = self.render(snap)
        self.assertNotIn("<b>x</b>", markup)
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", markup)


@integration_only
@needs_node
class TwoColumnTests(DeckCase):
    def test_middle_has_two_columns_with_all_panels(self):
        _, els = self.render()
        middle = next(el for el in els if el["tag"] == "main" and "middle" in classes(el))
        inside = [el for el in self.inside(els, middle) if el is not middle]
        direct = sorted((el for el in inside if not any(
            parent is not el and parent["start"] < el["start"]
            and el["start"] < parent["start"] + len(parent["markup"])
            for parent in inside)), key=lambda el: el["start"])
        self.assertEqual([(el["tag"], classes(el)) for el in direct],
                         [("div", ["col"]), ("div", ["col"])])
        for col, first in zip(direct, ("team:alpha", "focus")):
            panels = sorted((el for el in self.inside(els, col) if "data-panel" in el["attrs"]),
                            key=lambda el: el["start"])
            self.assertTrue(panels)
            self.assertEqual(panels[0]["attrs"]["data-panel"], first)
        names = [el["attrs"]["data-panel"] for el in inside if "data-panel" in el["attrs"]]
        for name in ("team:alpha", "team:beta", "halted", "focus", "log", "builds", "disk"):
            self.assertEqual(names.count(name), 1, name)
        self.assertEqual([name for el in els for name in classes(el) if name in ("dock", "tcol", "teams")], [])

    def test_fixture_places_teams_left_details_right_and_spills_builds_left(self):
        # The team list runs out first, so BUILDS spills into the left column. By hand, in rows: alpha 5.5 left,
        # focus 9.5 right, beta 3.5 and halted 3.5 left (12.5), log 5.5 right (15), BUILDS left, DISK right.
        _, els = self.render()
        cols = sorted((el for el in els if el["tag"] == "div" and classes(el) == ["col"]), key=lambda el: el["start"])
        order = [[el["attrs"]["data-panel"] for el in sorted(self.inside(els, col), key=lambda el: el["start"])
                  if "data-panel" in el["attrs"]] for col in cols]
        self.assertEqual(order, [["team:alpha", "team:beta", "halted", "builds"], ["focus", "log", "disk"]])


MOTION_CLASSES = ("pulse", "sweep", "flash", "flow")


@integration_only
@needs_node
class MotionTests(DeckCase):
    """Coord-b working (so its glyph breathes), all agents (Coord-a's running one flows), message 9 arrived."""

    def motion_snapshot(self):
        snap = snapshot()
        snap["teams"][0]["sessions"][2]["herdr"]["status"] = "working"
        return snap

    def found(self, els):
        return {name: [el for el in els if name in classes(el)] for name in MOTION_CLASSES}

    def test_motion_off_draws_still(self):
        _, els = self.render(self.motion_snapshot(), allAgents=True, flash=[["alpha", 9]], motion=False)
        self.assertEqual({k: len(v) for k, v in self.found(els).items()}, dict.fromkeys(MOTION_CLASSES, 0))

    def test_motion_on_animates_what_is_live(self):
        _, els = self.render(self.motion_snapshot(), allAgents=True, flash=[["alpha", 9]], motion=True)
        found = self.found(els)
        self.assertEqual([el["text"] for el in found["pulse"]], ["●"])
        self.assertTrue(all(el["start"] > self.session(els, "alpha/b")["start"] for el in found["pulse"]))
        self.assertEqual(len(found["sweep"]), 3)
        self.assertEqual(len(found["flow"]), 1)
        flashed = {el["attrs"].get("data-id") or el["text"][:8] for el in found["flash"]}
        self.assertEqual(flashed, {"alpha/a", "14:59:00"})


@integration_only
@needs_node
class FitTests(DeckCase):
    def test_long_mail_line_wraps_or_carries_its_text(self):
        snap = snapshot()
        snap["teams"][0]["sessions"][1]["mail"]["broadcasts"] = 0
        _, els = self.render(snap, cursor=1)
        row = self.row_with(els, self.panel(els, "focus"), "held 2")
        self.assertTrue("wrap" in classes(row) or "held 2" in (row["attrs"].get("title") or ""), row["markup"])

    def test_disk_worktree_with_many_parts_wraps_or_carries_its_text(self):
        snap = snapshot()
        snap["teams"][0]["disk"]["worktrees"][0]["parts"] = {"cargo-target": 12.0, "node_modules": 9.0,
                                                             ".codegraph": 3.0, "target": 1.0}
        _, els = self.render(snap)
        row = self.row_with(els, self.panel(els, "disk"), "target 1.0G")
        self.assertTrue("wrap" in classes(row) or "target 1.0G" in (row["attrs"].get("title") or ""), row["markup"])

    def test_lanes_pips_round_half_to_even(self):
        # 1 of 4 lanes in the team box's 10 cells is 2.5 cells; render._pips rounds half to even: 2 cells, 20%.
        snap = snapshot()
        snap["teams"][0].update(lanes_running=1, cap=4)
        _, els = self.render(snap)
        self.assertIn('<span class="pips" style="--cells:10"><i class="bg-blue" style="width:20.00%">',
                      self.panel(els, "team:alpha")["markup"])


@integration_only
@needs_node
class HandleKeyTests(unittest.TestCase):
    def key(self, key, ui=None):
        """{ui, action, before}: handleKey's result and the ui it was given, as it stood after the call."""
        script_ui = {**BASE_UI, **(ui or {})}
        return call_js("keys.js", "handleKey", key, script_ui, snapshot()), script_ui

    def test_down_and_up_move_and_clamp(self):
        for key in ("j", "ArrowDown"):
            self.assertEqual(self.key(key)[0]["ui"]["cursor"], 1)
            self.assertEqual(self.key(key, {"cursor": 3})[0]["ui"]["cursor"], 3)
        for key in ("k", "ArrowUp"):
            self.assertEqual(self.key(key, {"cursor": 2})[0]["ui"]["cursor"], 1)
            self.assertEqual(self.key(key)[0]["ui"]["cursor"], 0)

    def test_enter_toggles_the_cursor_session(self):
        self.assertEqual(self.key("Enter", {"cursor": 1})[0]["ui"]["expanded"], ["alpha/a"])
        self.assertEqual(self.key("Enter", {"cursor": 1, "expanded": ["alpha/a"]})[0]["ui"]["expanded"], [])

    def test_a_toggles_all_agents(self):
        self.assertIs(self.key("a")[0]["ui"]["allAgents"], True)
        self.assertIs(self.key("a", {"allAgents": True})[0]["ui"]["allAgents"], False)

    def test_t_toggles_team_agents(self):
        # t shows the team's agents; shift-T (the old key) does nothing now.
        self.assertIs(self.key("t")[0]["ui"]["teamAgents"], True)
        self.assertIs(self.key("t", {"teamAgents": True})[0]["ui"]["teamAgents"], False)
        self.assertIs(self.key("T")[0]["ui"]["teamAgents"], False)

    def test_a_and_t_each_turn_the_other_off(self):
        ui = self.key("t", {"allAgents": True})[0]["ui"]
        self.assertEqual((ui["teamAgents"], ui["allAgents"]), (True, False))
        ui = self.key("a", {"teamAgents": True})[0]["ui"]
        self.assertEqual((ui["allAgents"], ui["teamAgents"]), (True, False))
        self.assertEqual(self.key("t", {"teamFilter": "beta"})[0]["ui"]["teamFilter"], "beta")

    def test_f_cycles_teams_and_resets_the_cursor(self):
        for before, after in ((None, "alpha"), ("alpha", "beta"), ("beta", "gamma"), ("gamma", None)):
            result = self.key("f", {"teamFilter": before, "cursor": 2 if before is None else 0})[0]
            self.assertEqual(result["ui"]["teamFilter"], after)
            self.assertEqual(result["ui"]["cursor"], 0)

    def test_d_asks_for_disk_now(self):
        self.assertEqual(self.key("d")[0]["action"], "disk-now")

    def test_other_keys_have_no_action(self):
        for key in ("x", "q", "Escape"):
            result = self.key(key, {"cursor": 1})[0]
            self.assertIsNone(result["action"])
            self.assertEqual(result["ui"]["cursor"], 1)

    def test_input_is_not_mutated(self):
        script = (f"import {{ handleKey }} from {json.dumps((JS / 'keys.js').as_uri())};\n"
                  f"const snap = {json.dumps(snapshot())};\n"
                  f"const ui = {json.dumps(BASE_UI)};\n"
                  "const before = JSON.stringify(ui);\n"
                  "for (const key of ['j', 'k', 'Enter', 'a', 'T', 't', 'd']) handleKey(key, ui, snap);\n"
                  "process.stdout.write(JSON.stringify(JSON.stringify(ui) === before));\n")
        done = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True,
                              timeout=60)
        self.assertEqual(done.stdout, "true", done.stderr)


@integration_only
@needs_node
class VisibleTests(unittest.TestCase):
    def ids(self, team_filter):
        return [row["id"] for row in call_js("visible.js", "visible", snapshot(), team_filter)]

    def test_all_teams_match_render_visible(self):
        from codeteam2.deck import render
        expected = [sid for sid, _, _ in render.visible(snapshot(), None)]
        self.assertEqual(expected, ["alpha/orc", "alpha/a", "alpha/b", "beta/kong"])
        self.assertEqual(self.ids(None), expected)

    def test_team_filter_matches_render_visible(self):
        from codeteam2.deck import render
        expected = [sid for sid, _, _ in render.visible(snapshot(), "beta")]
        self.assertEqual(expected, ["beta/kong"])
        self.assertEqual(self.ids("beta"), expected)


class FakeCollector:
    def latest(self, now=None):
        return test_deck.render_snapshot(), []

    def disk_now(self):
        raise AssertionError("the page test never presses disk-now")


@integration_only
@needs_node
class ServedPageTests(unittest.TestCase):
    """The real web folder through build_server on 127.0.0.1, port 0, motion off."""

    def setUp(self):
        from codeteam2.deck.server.build_server import build_server

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, {"CODETEAM_DECK_LOG": str(Path(tmp.name) / "deck.log")})
        env.start()
        self.addCleanup(env.stop)
        self.server = build_server(FakeCollector(), port=0, web_dir=WEB, motion_on=False, interval=2.0)
        self.addCleanup(self.server.server_close)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)

    def get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        try:
            conn.request("GET", path)
            response = conn.getresponse()
            return response.status, response.read().decode("utf-8")
        finally:
            conn.close()

    def crawl(self):
        """{path: (status, text)} for / and everything it links, followed through every JS import."""
        seen, todo = {}, ["/"]
        while todo:
            path = todo.pop()
            if path in seen:
                continue
            seen[path] = self.get(path)
            text = seen[path][1]
            if path == "/" or path.endswith(".css"):
                todo += re.findall(r'(?:href|src)="(/[^"]*)"', text)
            if path.endswith(".js"):
                base = path.rsplit("/", 1)[0]
                todo += [f"{base}/{name.removeprefix('./')}"
                         for name in re.findall(r'(?:from|import)\s*["\'](\./[^"\']+)["\']', text)]
        return seen

    def test_page_is_served_with_motion_off(self):
        status, text = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn('data-motion="off"', text)
        self.assertIn('data-interval="2.0"', text)

    def test_every_linked_asset_and_import_answers(self):
        pages = self.crawl()
        self.assertIn("/js/main.js", pages)
        self.assertIn("/js/deck.js", pages)
        self.assertTrue(any(path.endswith(".css") for path in pages))
        self.assertEqual({path: status for path, (status, _) in pages.items() if status != 200}, {})

    def test_no_external_url(self):
        for path, (_, text) in self.crawl().items():
            with self.subTest(path):
                self.assertNotRegex(text, r"https?:")
                self.assertNotRegex(text, r'(?:href|src)="//|url\(\s*["\']?//|from\s*["\']//')


if __name__ == "__main__":
    unittest.main()
