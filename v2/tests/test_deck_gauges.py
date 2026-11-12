"""Tests for SPEC-deck-motion §B and the motion tags in render.py: heat colours, eighth-block bars, the focus box's
tool trace, turns sparkline and turns left, the new palette words, and the `~` tags render(motion=True) puts on
animated segments (plan deck-motion, "The contract between units (tags)" and Unit 2).

Fixtures come from test_deck; nothing here reads a file, a team or a terminal.
"""
import copy
import re
import unittest
from unittest.mock import patch

from test_deck import (NOW, RenderCase, a_session, a_team, colour_at, colour_of, find_box, render_snapshot,
                       row_text, stress_snapshot)

SPARK = "▁▂▃▄▅▆▇█"
WIDTHS = (60, 80, 120, 200)
# Twelve tool names, far wider together than any focus box body.
LONG_TRACE = ["Read", "Grep", "Edit", "Bash", "Read", "MultiEdit", "Bash", "Write", "Read", "Edit", "Bash",
              "TodoWrite"]
TURNS = [100, 200, 400, 800, {"compacted": True}, 100, 300]


def words(colour):
    return (colour or "").split()


def placed(rows):
    """(y, x, text, colour) for every segment, x counted in cells from the row's start."""
    out = []
    for y, row in enumerate(rows):
        x = 0
        for text, colour in row:
            out.append((y, x, text, colour))
            x += len(text)
    return out


def carrying(rows, word):
    return [p for p in placed(rows) if word in words(p[3])]


def strip_tags(rows):
    """rows with every `~` colour word removed; a colour left empty becomes None."""
    def clean(colour):
        if not any(w.startswith("~") for w in words(colour)):
            return colour
        return " ".join(w for w in words(colour) if not w.startswith("~")) or None
    return [[(text, clean(colour)) for text, colour in row] for row in rows]


def gauge(rows, key):
    """The joined text of the segments carrying `~ease:<key>`, checked to be one run on one row."""
    found = sorted(carrying(rows, f"~ease:{key}"), key=lambda p: (p[0], p[1]))
    assert found, f"no segment carries ~ease:{key}"
    assert len({p[0] for p in found}) == 1, f"~ease:{key} spans rows: {found}"
    for a, b in zip(found, found[1:]):
        assert a[1] + len(a[2]) == b[1], f"~ease:{key} is not one run: {found}"
    return "".join(p[2] for p in found)


def enrich(snap):
    """Every session gets a long tool trace, turns with a compaction, and a turns-left estimate."""
    for t in snap["teams"]:
        for s in t.get("sessions") or []:
            s["recent"] = {**(s.get("recent") or {}), "trace": list(LONG_TRACE)}
            s["turns"] = TURNS * 2
            s["turns_left"] = 123
    return snap


def working(snap, name="Orc-Alpha"):
    s = a_session(snap, name)
    s["herdr"]["status"] = "working"
    s["flags"]["between_turns"] = False
    return snap


class HeatColourTests(RenderCase):
    """B1: the context colour follows its fill: green < 30, amber from 30, orange from 40, salmon from 50."""

    HEAT = ((29, "green"), (30, "amber"), (40, "orange"), (50, "salmon"))

    def test_ctx_colour_thresholds(self):
        for pct, colour in ((29, "green"), (30, "amber"), (39.9, "amber"), (40, "orange"), (50, "salmon"),
                            (None, "amber")):
            with self.subTest(pct=pct):
                self.assertEqual(self.r._ctx_colour(pct), colour)

    def at(self, pct):
        snap = copy.deepcopy(self.snap)
        a_session(snap, "Orc-Alpha")["context"]["used_pct"] = pct
        return self.rows(snap, cursor=0)

    def test_the_session_row_bar_and_percent_take_the_heat_colour(self):
        for pct, colour in self.HEAT:
            with self.subTest(pct=pct):
                row, text, x0 = self.line(self.box(self.at(pct), "alpha · 3 sessions"), "Orc-Alpha")
                self.assertWord(colour_of(row, "█", x0), colour, "row bar")
                self.assertWord(colour_of(row, f"{pct}%", x0), colour, "row percent")

    def test_the_focus_bar_and_percent_take_the_heat_colour_and_the_percent_is_bold(self):
        for pct, colour in self.HEAT:
            with self.subTest(pct=pct):
                row, text, x0 = self.line(self.box(self.at(pct), "Opus 5.5 · Orc-Alpha"), "ctx ")
                self.assertWord(colour_of(row, "█", x0), colour, "focus bar")
                self.assertWord(colour_of(row, f"{pct}%", x0), colour, "focus percent")
                self.assertWord(colour_of(row, f"{pct}%", x0), "bold", "focus percent")


class BarTests(RenderCase):
    """B2: _bar(value, maximum, cells, colour), `▕` + cells eighth-block cells + `▏`."""

    def bar(self, value, maximum=80, cells=10):
        return self.r._bar(value, maximum, cells, "green")

    def test_bar_text_at_every_step_the_spec_names(self):
        for value, inner in ((0, " " * 10), (1, "▏" + " " * 9), (79, "█" * 9 + "▉"), (80, "█" * 10),
                             (500, "█" * 10)):
            with self.subTest(value=value):
                self.assertEqual(row_text(self.bar(value)), f"▕{inner}▏")

    def test_any_value_above_zero_shows_at_least_one_eighth(self):
        self.assertEqual(row_text(self.bar(0.01)), "▕▏" + " " * 9 + "▏")

    def test_filled_cells_are_in_the_colour_and_spaces_and_edges_are_faint(self):
        for value in (1, 41, 79):
            row = self.bar(value)
            text = row_text(row)
            with self.subTest(value=value):
                for col, char in enumerate(text):
                    edge = col in (0, len(text) - 1)
                    expected = "faint" if edge or char == " " else "green"
                    self.assertWord(colour_at(row, col), expected, f"cell {col} {char!r} of {text!r}")

    def test_an_unreadable_bar_is_an_amber_question_mark(self):
        for value, maximum in ((None, 80), (5, None), (5, 0), (float("nan"), 80)):
            with self.subTest(value=value, maximum=maximum):
                row = self.r._bar(value, maximum, 10, "green")
                self.assertEqual(row_text(row), "?")
                self.assertWord(colour_at(row, 0), "amber", "unreadable")

    def test_context_budget_swap_and_disk_draw_bars_and_lanes_keep_pips(self):
        rows = self.rows(cursor=0)
        texts = [row_text(r) for r in rows]
        screen = "\n".join(texts)
        # 42% of 6 cells is 20 eighths; of 10 cells 34; budget 3/6 of 6 is 24; swap 0.5 of 5 is 20;
        # DISK alpha 80/95 of 12 cells is 81, gamma is full.
        self.assertIn("▕██▌   ▏ 42%", self.line(self.box(rows, "alpha · 3 sessions"), "Orc-Alpha")[1])
        self.assertIn("ctx ▕████▎     ▏ 42%", self.box_text(rows, "Opus 5.5 · Orc-Alpha"))
        builds = self.box_text(rows, "BUILDS · queue")
        self.assertIn("budget ▕███   ▏ 3/6", builds)
        self.assertIn("swap ▕██▌  ▏ 50%", builds)
        disk = self.box(rows, "DISK")
        self.assertIn("▕" + "█" * 10 + "▏ ▏", self.line(disk, "alpha")[1])
        self.assertIn("▕" + "█" * 12 + "▏", self.line(disk, "gamma")[1])
        self.assertIn("▰▰▰▰▰▱▱▱▱▱ 1/2 lanes", screen)
        self.assertIn("▰▰▰▱▱▱ 1/2", screen)


class ToolTraceTests(RenderCase):
    """B3: the focus box's `tools read → edit → bash` row."""

    def tools_line(self, snap, cursor=0, width=120, model="Opus 5.5", name="Orc-Alpha", **kwargs):
        rows = self.rows(snap, width, cursor=cursor, **kwargs)
        row, text, x0 = self.line(self.box(rows, f"{model} · {name}"), "tools ")
        return row, text[2:-2].rstrip(), x0, len(text) - 4

    def test_the_trace_is_lower_cased_oldest_first(self):
        snap = copy.deepcopy(self.snap)
        a_session(snap, "Orc-Alpha")["recent"]["trace"] = ["Read", "Edit", "Bash"]
        self.assertIn("tools read → edit → bash", self.tools_line(snap)[1])

    def test_without_a_trace_the_recent_tool_names_are_used(self):
        _, body, _, _ = self.tools_line(self.snap)
        self.assertIn("tools read", body)

    def test_the_trace_wins_over_the_recent_tools(self):
        snap = copy.deepcopy(self.snap)
        a_session(snap, "Orc-Alpha")["recent"]["trace"] = ["Grep"]
        _, body, _, _ = self.tools_line(snap)
        self.assertIn("tools grep", body)
        self.assertNotIn("read", body)

    def test_the_oldest_give_way_at_a_narrow_width_behind_a_leading_ellipsis(self):
        snap = copy.deepcopy(self.snap)
        a_session(snap, "Orc-Alpha")["recent"]["trace"] = list(LONG_TRACE)
        names = [n.lower() for n in LONG_TRACE]
        for width in (60, 120):
            with self.subTest(width=width):
                _, body, _, room = self.tools_line(snap, width=width)
                self.assertTrue(body.startswith("tools … → "), body)
                self.assertLessEqual(len(body), room, body)
                shown = body[len("tools … → "):].split(" → ")
                self.assertEqual(shown, names[-len(shown):], body)
                longer = "tools … → " + " → ".join(names[-len(shown) - 1:])
                self.assertGreater(len(longer), room, f"{body!r} gave way more than the width needs")

    def test_no_tools_is_a_dim_dash(self):
        row, body, x0, _ = self.tools_line(self.snap, cursor=2, model="Sonnet 4.6", name="Coord-b")
        self.assertIn("tools –", body)
        self.assertWord(colour_of(row, "–", x0), "dim", "no tools")

    def test_the_expanded_detail_still_lists_every_tool_with_its_summary(self):
        snap = copy.deepcopy(self.snap)
        a_session(snap, "Orc-Alpha")["recent"]["trace"] = ["Grep", "Edit"]
        body = self.box_text(self.rows(snap, cursor=0, expanded={"alpha/orc"}), "Opus 5.5 · Orc-Alpha")
        self.assertIn("tool Read render.py", body)


class TurnsTests(RenderCase):
    """B4 and B5: the focus box's `turns ▁▂▃▅↓▁▃  ~24 turns left` row."""

    def turns_line(self, **fields):
        snap = copy.deepcopy(self.snap)
        a_session(snap, "Orc-Alpha").update(fields)
        row, text, x0 = self.line(self.box(self.rows(snap, cursor=0), "Opus 5.5 · Orc-Alpha"), "turns ")
        return row, text, x0

    def test_the_sparkline_scales_turns_to_the_largest_and_marks_a_compaction(self):
        row, text, x0 = self.turns_line(turns=TURNS)
        spark = re.search(r"turns (\S+)", text)[1]
        self.assertEqual(len(spark), len(TURNS), text)
        self.assertEqual(spark[4], "↓", text)
        self.assertWord(colour_of(row, "↓", x0), "sky", "compaction")
        bars = spark[:4] + spark[5:]
        self.assertTrue(set(bars) <= set(SPARK), text)
        self.assertEqual(spark[3], "█", "the largest turn is a full block")
        levels = [SPARK.index(c) for c in spark[:4]]
        self.assertEqual(levels, sorted(levels), text)
        self.assertLess(levels[0], levels[3], text)
        self.assertEqual(spark[0], spark[5], "equal turns draw equal glyphs")

    def test_missing_turns_are_an_amber_question_mark(self):
        row, text, x0 = self.turns_line()
        self.assertIn("turns ?", text)
        self.assertWord(colour_of(row, "?", x0 + text.index("turns ")), "amber", "missing turns")

    def test_no_turns_yet_is_a_dim_dash(self):
        row, text, x0 = self.turns_line(turns=[])
        self.assertIn("turns –", text)
        self.assertWord(colour_of(row, "–", x0 + text.index("turns ")), "dim", "empty turns")

    def test_turns_left_is_coloured_by_how_many_are_left(self):
        for left, colour in ((31, "green"), (30, "amber"), (16, "amber"), (15, "orange"), (6, "orange"),
                             (5, "salmon")):
            with self.subTest(left=left):
                row, text, x0 = self.turns_line(turns=TURNS, turns_left=left)
                self.assertIn(f"~{left} turns left", text)
                self.assertWord(colour_of(row, f"~{left}", x0), colour, f"{left} left")

    def test_no_estimate_leaves_turns_left_out(self):
        _, text, _ = self.turns_line(turns=TURNS, turns_left=None)
        self.assertNotIn("turns left", text)


class PaletteTests(RenderCase):
    """The palette words §B and the pulse add."""

    def test_palette_256_carries_orange_and_the_pulse_shades(self):
        got = self.r.palette(256)
        self.assertEqual({w: got.get(w) for w in ("orange", "pulse2", "pulse3")},
                         {"orange": 215, "pulse2": 72, "pulse3": 65})

    def test_palette_16_falls_back_to_yellow_green_and_dim(self):
        import curses
        got = self.r.palette(16)
        self.assertEqual(got.get("orange"), curses.COLOR_YELLOW)
        self.assertEqual(got.get("pulse2"), curses.COLOR_GREEN)
        self.assertIn("pulse3", got)
        self.assertEqual(got["pulse3"], got["dim"])


class FakeScreen:
    def __init__(self, height, width):
        self.size, self.calls = (height, width), []

    def getmaxyx(self):
        return self.size

    def erase(self):
        pass

    def refresh(self):
        pass

    def addstr(self, y, x, text, attr):
        self.calls.append((y, x, text, attr))


class MotionTagTests(RenderCase):
    """render(motion=True) tags animated segments with `~` words; motion=False carries none."""

    def moving(self, snap=None, **kwargs):
        return self.rows(snap, motion=True, **kwargs)

    def test_pulse_sits_on_a_working_sessions_glyph_in_its_row_and_the_focus_caption(self):
        rows = self.moving(working(copy.deepcopy(self.snap)), cursor=0)
        texts = [row_text(r) for r in rows]
        y_row = next(y for y, t in enumerate(texts) if "▸● Orc-Alpha" in t)
        y_cap, x0, _ = find_box(texts, "Opus 5.5 · Orc-Alpha")
        expected = {(y_row, texts[y_row].index("● Orc-Alpha")), (y_cap, texts[y_cap].index("● working", x0))}
        pulses = carrying(rows, "~pulse")
        self.assertEqual({(y, x) for y, x, _, _ in pulses}, expected, pulses)
        for _, _, text, colour in pulses:
            self.assertTrue(text.startswith("●"), text)
            self.assertEqual(words(colour)[0], "green", colour)

    def test_no_pulse_when_idle_done_between_turns_or_blocked(self):
        for status, between in (("idle", False), ("done", False), ("working", True), ("blocked", False)):
            snap = copy.deepcopy(self.snap)
            s = a_session(snap, "Orc-Alpha")
            s["herdr"]["status"] = status
            s["flags"]["between_turns"] = between
            with self.subTest(status=status, between=between):
                self.assertEqual(carrying(self.moving(snap, cursor=0), "~pulse"), [])

    def test_sweep_sits_on_the_running_strip_segment_only(self):
        rows = self.moving()
        sweeps = carrying(rows, "~sweep")
        self.assertEqual(len(sweeps), 1, sweeps)
        y, x, text, colour = sweeps[0]
        self.assertEqual(text, "███", "three running jobs")
        self.assertEqual(words(colour)[0], "green", colour)
        y_box, x0, _ = find_box([row_text(r) for r in rows], "BUILDS · queue")
        self.assertEqual((y, x), (y_box + 1, x0 + 2), "the strip is the box's first body row")

    def test_flow_sits_on_an_unfinished_agents_lane_only(self):
        rows = self.moving(cursor=1)
        texts = [row_text(r) for r in rows]
        flows = carrying(rows, "~flow")
        self.assertEqual(len(flows), 1, flows)
        y, x, text, _ = flows[0]
        self.assertEqual(set(text), {"━"}, text)
        self.assertIn("2: port", texts[y], "the running agent's row, not the finished one's")

    def test_a_stalled_agent_does_not_flow(self):
        snap = copy.deepcopy(self.snap)
        a_session(snap, "Coord-a")["agents"][0]["flags"]["stalled"] = True
        self.assertEqual(carrying(self.moving(snap, cursor=1), "~flow"), [])

    def inner(self, rows, title, needle):
        """(y, x0 + 2, x1 - 1): the body columns of the box line holding needle."""
        box = self.box(rows, title)
        y = next(y for y, r in enumerate(rows) if r is self.line(box, needle)[0])
        _, x0, x1 = find_box([row_text(r) for r in rows], title)
        return y, x0 + 2, x1 - 1

    def flashed(self, rows, tag, where):
        """Every non-blank segment inside where carries tag; the borders do not."""
        y, start, end = where
        inside = [p for p in placed(rows) if p[0] == y and start <= p[1] < end and p[2].strip()]
        self.assertTrue(inside)
        for p in inside:
            self.assertIn(tag, words(p[3]), p)
        border = [p for p in placed(rows) if p[0] == y and p[1] in (start - 2, end)]
        for p in border:
            self.assertNotIn(tag, words(p[3]), p)

    def test_flash_lights_the_log_line_and_the_recipients_row_and_nothing_else(self):
        rows = self.moving(cursor=0, flash={("alpha", 9)})
        log = self.inner(rows, "log · alpha", "REQUEST")
        row = self.inner(rows, "alpha · 3 sessions", "Coord-a")
        self.flashed(rows, "~flash:alpha:9", log)
        self.flashed(rows, "~flash:alpha:9", row)
        for y, x, text, colour in placed(rows):
            if any(w.startswith("~flash") for w in words(colour)):
                self.assertTrue(any(y == wy and s <= x < e for wy, s, e in (log, row)), (y, x, text, colour))

    def test_no_flash_without_a_flash_set(self):
        for flash in (None, set()):
            with self.subTest(flash=flash):
                rows = self.moving(cursor=0, flash=flash)
                self.assertEqual([p for p in placed(rows) if any(w.startswith("~flash") for w in words(p[3]))],
                                 [])

    def newer(self, recipient):
        snap = copy.deepcopy(self.snap)
        a_team(snap, "alpha")["messages"]["last"].insert(
            0, {"id": 10, "ts": NOW - 30, "sender": "Orc-Alpha", "kind": "NOTE", "recipient": recipient,
                "text": "and another"})
        return snap

    def test_a_recipient_named_by_its_key_flashes(self):
        rows = self.moving(self.newer("b"), cursor=0, flash={("alpha", 10)})
        self.flashed(rows, "~flash:alpha:10", self.inner(rows, "alpha · 3 sessions", "Coord-b"))

    def test_broadcast_flashes_only_the_resolved_target_row(self):
        snap = self.newer("all")
        a_team(snap, "alpha")["messages"]["last"][0]["target"] = "b"
        rows = self.moving(snap, cursor=0, flash={("alpha", 10)})
        self.flashed(rows, "~flash:alpha:10", self.inner(rows, "alpha · 3 sessions", "Coord-b"))
        for name in ("Orc-Alpha", "Coord-a"):
            y, start, end = self.inner(rows, "alpha · 3 sessions", name)
            self.assertFalse([p for p in carrying(rows, "~flash:alpha:10") if p[0] == y and start <= p[1] < end])

    def test_comma_list_flashes_only_the_resolved_target_row(self):
        snap = self.newer("Coord-a,Coord-b")
        a_team(snap, "alpha")["messages"]["last"][0]["target"] = "a"
        rows = self.moving(snap, cursor=0, flash={("alpha", 10)})
        self.flashed(rows, "~flash:alpha:10", self.inner(rows, "alpha · 3 sessions", "Coord-a"))
        for name in ("Orc-Alpha", "Coord-b"):
            y, start, end = self.inner(rows, "alpha · 3 sessions", name)
            self.assertFalse([p for p in carrying(rows, "~flash:alpha:10") if p[0] == y and start <= p[1] < end])

    def test_message_without_target_matches_recipient_name_or_key(self):
        for recipient in ("Coord-a", "a"):
            with self.subTest(recipient=recipient):
                rows = self.moving(self.newer(recipient), cursor=0, flash={("alpha", 10)})
                self.flashed(rows, "~flash:alpha:10", self.inner(rows, "alpha · 3 sessions", "Coord-a"))
                for name in ("Orc-Alpha", "Coord-b"):
                    y, start, end = self.inner(rows, "alpha · 3 sessions", name)
                    self.assertFalse([p for p in carrying(rows, "~flash:alpha:10")
                                      if p[0] == y and start <= p[1] < end])

    def test_unknown_target_flashes_the_log_but_no_session_row(self):
        snap = self.newer("Coord-a")
        a_team(snap, "alpha")["messages"]["last"][0]["target"] = "missing"
        rows = self.moving(snap, cursor=0, flash={("alpha", 10)})
        self.flashed(rows, "~flash:alpha:10", self.inner(rows, "log · alpha", "and a"))
        for name in ("Orc-Alpha", "Coord-a", "Coord-b"):
            y, start, end = self.inner(rows, "alpha · 3 sessions", name)
            self.assertFalse([p for p in carrying(rows, "~flash:alpha:10") if p[0] == y and start <= p[1] < end])

    def test_a_row_named_by_several_flashed_messages_carries_the_newest(self):
        rows = self.moving(self.newer("Coord-a"), cursor=0, flash={("alpha", 9), ("alpha", 10)})
        where = self.inner(rows, "alpha · 3 sessions", "Coord-a")
        self.flashed(rows, "~flash:alpha:10", where)
        y, start, end = where
        self.assertFalse([p for p in placed(rows) if p[0] == y and start <= p[1] < end
                          and "~flash:alpha:9" in words(p[3])])

    def test_every_gauge_carries_its_ease_key_on_its_whole_gauge(self):
        rows = self.moving(cursor=0)
        expected = {"row:alpha/orc:ctx": "▕██▌   ▏", "focus:alpha/orc:ctx": "▕████▎     ▏",
                    "row:alpha/a:ctx": "▕█████▏▏",
                    "builds:budget": "▕███   ▏", "builds:swap": "▕██▌  ▏",
                    "disk:alpha": "▕" + "█" * 10 + "▏ ▏", "disk:gamma": "▕" + "█" * 12 + "▏",
                    "lanes:alpha:fleet": "▰▰▰▱▱▱", "lanes:alpha:box": "▰▰▰▰▰▱▱▱▱▱"}
        for key, text in expected.items():
            with self.subTest(key=key):
                self.assertEqual(gauge(rows, key), text)
        for key, pattern in (("row:alpha/orc:ctx:n", r"42%"), ("focus:alpha/orc:ctx:n", r"42%"),
                             ("row:alpha/a:ctx:n", r"85%"), ("builds:budget:n", r"3(/6)?"),
                             ("builds:swap:n", r"50%")):
            with self.subTest(key=key):
                self.assertRegex(gauge(rows, key).strip(), f"^{pattern}$")

    def test_a_segment_can_carry_several_tags_with_the_palette_word_first(self):
        snap = working(copy.deepcopy(self.snap))
        a_team(snap, "alpha")["messages"]["last"][0]["recipient"] = "Orc-Alpha"
        rows = self.moving(snap, cursor=0, flash={("alpha", 9)})
        both = [p for p in carrying(rows, "~pulse") if "~flash:alpha:9" in words(p[3])]
        self.assertEqual(len(both), 1, "the row's glyph pulses and flashes; the caption only pulses")
        self.assertEqual(words(both[0][3])[0], "green", both[0])

    def test_motion_off_carries_no_tilde_word_at_any_width(self):
        for name, snap in (("render", working(enrich(render_snapshot()))), ("stress", enrich(stress_snapshot()))):
            for width in WIDTHS:
                for height in (None, 40):
                    with self.subTest(snap=name, width=width, height=height):
                        rows = self.rows(snap, width, cursor=1, height=height, flash={("alpha", 9)})
                        tagged = [p for p in placed(rows) if any(w.startswith("~") for w in words(p[3]))]
                        self.assertEqual(tagged, [])

    def test_motion_on_with_its_tags_stripped_is_motion_off(self):
        for name, snap in (("render", working(enrich(render_snapshot()))), ("stress", enrich(stress_snapshot()))):
            for width in WIDTHS:
                for height in (None, 40):
                    with self.subTest(snap=name, width=width, height=height):
                        kwargs = {"cursor": 1, "height": height, "flash": {("alpha", 9)}}
                        self.assertEqual(strip_tags(self.rows(snap, width, motion=True, **kwargs)),
                                         self.rows(snap, width, **kwargs))

    def test_draw_ignores_tilde_words(self):
        plain = [[("● ", "green"), ("x", None)]]
        tagged = [[("● ", "green ~pulse ~flash:alpha:9"), ("x", "~flash:alpha:9")]]
        screens = []
        with patch("curses.start_color"), patch("curses.use_default_colors"), patch("curses.init_pair"), \
                patch("curses.color_pair", side_effect=lambda n: n << 8), patch("curses.COLORS", 256, create=True):
            for rows in (plain, tagged):
                screen = FakeScreen(3, 10)
                try:
                    self.r.draw(screen, rows)
                except KeyError as e:
                    self.fail(f"draw looked up a ~ word: {e}")
                screens.append(screen.calls)
        self.assertEqual(screens[1], screens[0])


class WidthTests(RenderCase):
    """Bars and the new focus rows still fit: no row is wider than the screen."""

    def test_every_row_fits_the_width_with_motion_off_and_on(self):
        for name, snap in (("render", working(enrich(render_snapshot()))), ("stress", enrich(stress_snapshot()))):
            for width in WIDTHS:
                for motion in (False, True):
                    for view in ({}, {"cursor": 1, "expanded": {"alpha/a"}}, {"height": 40}):
                        with self.subTest(snap=name, width=width, motion=motion, view=view):
                            for row in self.rows(snap, width, motion=motion, **view):
                                self.assertLessEqual(sum(len(t) for t, _ in row), width, row_text(row))


if __name__ == "__main__":
    unittest.main()
