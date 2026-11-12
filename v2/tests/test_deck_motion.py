"""Tests for the deck's motion (SPEC-deck-motion §A): the engine in codeteam2.deck.motion over hand-built tagged rows,
the app's --no-motion and its environment switches, and the engine over render(motion=True).

Rows are render's shape: lists of (text, colour) segments, an animated segment carrying `~` colour words after its
palette word. motion is imported in each class's setUp, so a class whose module is missing fails on its own.
"""
import contextlib
import io
import math
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

V2 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(V2))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import integration_only  # noqa: E402
from test_deck import (FakeDeckHerdr, NOW, queue_class, render_agent, render_job,  # noqa: E402
                       render_messages, render_queue, render_session, render_snapshot)

PULSE_SHADES = {"green", "pulse2", "pulse3"}
CTX_KEY = "row:alpha/a:ctx"
FLASH_KEYS = {("alpha", 41), "alpha:41"}


def words(colour):
    return frozenset((colour or "").split())


def grid(rows):
    """{(y, x): (character, colour words)} for every cell of the rows."""
    out = {}
    for y, row in enumerate(rows):
        x = 0
        for text, colour in row:
            for ch in text:
                out[(y, x)] = (ch, words(colour))
                x += 1
    return out


def tagged_span(cells):
    """The (y, x) cells covered by motion.cells' tagged segments."""
    return {(y, x + i) for y, x, text, _, _ in cells for i in range(len(text))}


def changed(a, b):
    return {pos for pos in a.keys() | b.keys() if a.get(pos) != b.get(pos)}


def gauge(rows, x0, width, y=0):
    """The text and colour words of the cells y, x0..x0+width-1 of rows."""
    g = grid(rows)
    return "".join(g[(y, x)][0] for x in range(x0, x0 + width)), [g[(y, x)][1] for x in range(x0, x0 + width)]


def mail_snapshot(max_id=41, ids=(41, 40)):
    """alpha's log holds ids, max_id given; beta's messages are unreadable (None), as collect gives a failed store."""
    last = [{"id": i, "ts": NOW, "sender": "Orc-Alpha", "kind": "REQUEST", "recipient": "Coord-a", "text": "hi"}
            for i in ids]
    return {"teams": [{"name": "alpha", "messages": {"max_id": max_id, "last": last}},
                      {"name": "beta", "messages": None}]}


def fleet_snapshot():
    """8 up teams, 60 sessions (7 or 8 each), every session working with a running subagent, and two more running
    jobs in every build class on top of render_queue's: the most motion the deck can show."""
    teams = []
    for n in range(8):
        name = f"team-{n}"
        sessions = [render_session(name, f"s{k}", f"Lane-{n}-{k}", "lane", status="working",
                                   agents=[render_agent(f"a{n}{k}")]) for k in range(8 if n < 4 else 7)]
        teams.append({"name": name, "manifest": f"/m/{name}.toml", "home": f"/t/{name}/team", "root": f"/t/{name}",
                      "state": "up", "heartbeat_age_s": 5, "cap": 4, "running": len(sessions), "lanes_running": 2,
                      "mail_waiting": 0, "msgs_last_hour": 7, "free_gb": 300.0, "messages": render_messages(),
                      "disk": {"size_gb": 20.0 + n, "worktrees": [{"path": f"/t/{name}/wt", "size_gb": 10.0,
                                                                    "parts": {"target": 2.0}}]},
                      "sessions": sessions})
    queue = render_queue()
    for cls in ("full", "post", "pre", "dev"):
        queue_class(queue, cls)["running"] += [
            render_job(f"{cls}-r{i}", cls, "running", team=f"team-{i}", session=f"Lane-{i}-0", started=NOW - 60,
                       pid=7000 + i, cost=1.0, running_s=60, pid_alive=True) for i in range(2)]
    builds = {"queue": queue, "warms": [], "largest": [], "procs": {}}
    return {"version": 1, "at": NOW, "took_s": 0.1, "errors": [], "volume": {"free_gb": 300.0}, "teams": teams,
            "builds": builds, "disk_at": NOW - 600, "alerts": []}


class MotionTests(unittest.TestCase):
    """motion.py on hand-built tagged rows: the switch, strip, cells and the frames."""

    def setUp(self):
        from codeteam2.deck import motion
        self.m = motion

    def frame_at(self, rows, t, state=None):
        return self.m.frame(rows, t, self.m.State() if state is None else state)

    # integration: starts a real Python child process
    @integration_only
    def test_importing_motion_does_not_import_curses(self):
        code = "import sys; import codeteam2.deck.motion; print('curses' in sys.modules)"
        out = subprocess.run([sys.executable, "-c", code], cwd=V2, capture_output=True, text=True, timeout=30)
        self.assertEqual(out.stdout.strip(), "False", out.stderr)

    def test_enabled_is_off_with_the_no_motion_flag(self):
        self.assertTrue(self.m.enabled(False, {"TERM": "xterm-256color"}))
        self.assertFalse(self.m.enabled(True, {"TERM": "xterm-256color"}))

    def test_enabled_is_off_when_no_motion_is_set_non_empty(self):
        self.assertFalse(self.m.enabled(False, {"NO_MOTION": "1", "TERM": "xterm-256color"}))
        self.assertTrue(self.m.enabled(False, {"NO_MOTION": "", "TERM": "xterm-256color"}))

    def test_enabled_is_off_on_a_dumb_terminal(self):
        self.assertFalse(self.m.enabled(False, {"TERM": "dumb"}))

    def test_strip_removes_every_tilde_word_and_leaves_an_emptied_colour_none(self):
        rows = [[("ab", None), ("●", "green ~pulse"), ("x", "dim")],
                [("▰▰", "~ease:row:alpha/a:ctx"), ("━━", "green bold ~flow ~flash:alpha:41")]]
        self.assertEqual(self.m.strip(rows), [[("ab", None), ("●", "green"), ("x", "dim")],
                                              [("▰▰", None), ("━━", "green bold")]])

    def test_strip_leaves_untagged_rows_as_they_are(self):
        rows = [[("plain ", None), ("text", "blue bold")], []]
        self.assertEqual(self.m.strip(rows), rows)

    def test_cells_lists_the_tagged_segments_with_x_in_cells_and_their_effects(self):
        rows = [[("▰▰", "green"), ("●", "green ~pulse"), (" ", None), ("██", "teal ~sweep")],
                [("─", "dim"), ("━━━", "blue ~flow ~flash:alpha:41")],
                [("ctx ", None), ("▰", "green ~ease:row:alpha/a:ctx"), ("▱", "~ease:row:alpha/a:ctx")]]
        got = sorted(self.m.cells(rows), key=lambda c: (c[0], c[1]))
        self.assertEqual([c[:4] for c in got], [(0, 2, "●", "green"), (0, 4, "██", "teal"), (1, 1, "━━━", "blue"),
                                                (2, 4, "▰", "green"), (2, 5, "▱", None)])
        effects = [c[4] for c in got]
        self.assertEqual(effects[0], (("pulse", None),))
        self.assertEqual(effects[1], (("sweep", None),))
        self.assertEqual(len(effects[2]), 2, effects[2])
        self.assertEqual(effects[2][0], ("flow", None))
        self.assertEqual(effects[2][1][0], "flash")
        self.assertIn(effects[2][1][1], FLASH_KEYS)
        self.assertEqual(effects[3], (("ease", CTX_KEY),))
        self.assertEqual(effects[4], (("ease", CTX_KEY),))

    def test_two_frames_differ_only_inside_tagged_segments(self):
        rows = [[("ab ", None), ("●", "green ~pulse"), (" Lane-a ", "blue"), ("████", "teal ~sweep"), (" end", "dim")],
                [("agent ", None), ("━━━━━━", "blue ~flow"), (" ok", None)],
                [("ctx ", None), ("▰▰", "green ~ease:row:alpha/a:ctx"), ("▱▱▱▱", "faint ~ease:row:alpha/a:ctx")]]
        cells = self.m.cells(rows)
        state = self.m.State()
        state.retarget(cells)
        fps = self.m.FPS
        a, b = (grid(self.frame_at(rows, 10.0 + k / fps, state)) for k in (0.5, 2.5))
        diff = changed(a, b)
        self.assertTrue(diff, "the frames are identical")
        self.assertLessEqual(diff, tagged_span(cells))
        still = grid(self.m.strip(rows))
        for pos in still.keys() - tagged_span(cells):
            self.assertEqual(a[pos], still[pos], pos)
            self.assertEqual(b[pos], still[pos], pos)

    def test_a_frame_carries_no_tilde_word(self):
        rows = [[("●", "green ~pulse"), ("██", "teal ~sweep"), ("━━", "blue ~flow ~flash:alpha:41")]]
        for _, colour in self.frame_at(rows, 3.3)[0]:
            self.assertFalse(any(w.startswith("~") for w in words(colour)), colour)

    def test_pulse_at_phase_zero_is_the_still_frame(self):
        rows = [[("ab ", None), ("●", "green ~pulse"), (" Lane-a", "blue")]]
        for t in (0.0, 3 * self.m.PULSE_S):
            self.assertEqual(grid(self.frame_at(rows, t)), grid(self.m.strip(rows)), t)

    def test_pulse_changes_shade_within_one_pulse(self):
        rows = [[("●", "green ~pulse")]]
        shades = set()
        for k in range(self.m.FPS):
            colour = grid(self.frame_at(rows, k * self.m.PULSE_S / self.m.FPS))[(0, 0)][1]
            self.assertEqual(len(colour), 1, colour)
            shades |= colour
        self.assertEqual(shades, PULSE_SHADES)

    def assert_head_moves(self, text, colour, effect):
        rows = [[("ab", None), (text, f"{colour} ~{effect}")]]
        cycle = len(text) + 2
        for k in range(2 * cycle + 1):
            g = grid(self.frame_at(rows, (k + 0.5) / self.m.FPS))
            for i in range(len(text)):
                want = {"sky", "bold"} if i == k % cycle else {colour}
                self.assertEqual(g[(0, 2 + i)], (text[i], want), f"frame {k} cell {i}")

    def test_sweep_head_moves_one_cell_a_frame_and_wraps(self):
        self.assert_head_moves("████", "teal", "sweep")

    def test_flow_head_moves_one_cell_a_frame_and_wraps(self):
        self.assert_head_moves("━━━━━", "blue", "flow")

    def test_one_cell_sweep_is_lit_then_dark_for_two_frames(self):
        rows = [[("█", "teal ~sweep")]]
        state = self.m.State()
        for tick, colour in enumerate(({"sky", "bold"}, {"teal"}, {"teal"}, {"sky", "bold"})):
            with self.subTest(tick=tick):
                frame = self.m.frame(rows, (tick + 0.5) / self.m.FPS, state)
                self.assertEqual(grid(frame)[(0, 0)], ("█", colour))

    def test_three_cell_flow_has_two_dark_frames_before_restart(self):
        rows = [[("━━━", "blue ~flow")]]
        state = self.m.State()
        for tick, head in enumerate((0, 1, 2, None, None, 0)):
            with self.subTest(tick=tick):
                frame = grid(self.m.frame(rows, (tick + 0.5) / self.m.FPS, state))
                for x in range(3):
                    colour = {"sky", "bold"} if x == head else {"blue"}
                    self.assertEqual(frame[(0, x)], ("━", colour))

    def test_frame_cells_redraws_one_cell_sweep_only_when_it_changes(self):
        tagged = self.m.cells([[('█', 'teal ~sweep')]])
        state = self.m.State()
        for tick, expected in enumerate(([(0, 0, '█', 'sky bold')], [(0, 0, '█', 'teal')], [],
                                         [(0, 0, '█', 'sky bold')])):
            with self.subTest(tick=tick):
                self.assertEqual(self.m.frame_cells(tagged, (tick + 0.5) / self.m.FPS, state), expected)

    def test_arrived_flashes_only_ids_above_the_previous_max(self):
        state = self.m.State()
        self.assertEqual(state.arrived(mail_snapshot(), {"alpha": 40}, 100.0), {("alpha", 41)})

    def test_nothing_flashes_on_the_first_refresh(self):
        state = self.m.State()
        self.assertEqual(state.arrived(mail_snapshot(), {}, 100.0), set())
        rows = [[("log", "blue ~flash:alpha:41")]]
        self.assertEqual(grid(self.frame_at(rows, 100.5, state)), grid(self.m.strip(rows)))

    def flash_colour(self, rows, t, state):
        return grid(self.m.frame(rows, t, state))[(0, 0)][1]

    def test_a_flash_is_amber_bold_until_flash_s_then_as_given(self):
        state = self.m.State()
        state.arrived(mail_snapshot(), {"alpha": 40}, 100.0)
        rows = [[("log", "blue ~flash:alpha:41")]]
        self.assertEqual(self.flash_colour(rows, 100.0, state), {"amber", "bold"})
        self.assertEqual(self.flash_colour(rows, 100.0 + self.m.FLASH_S - 0.1, state), {"amber", "bold"})
        self.assertEqual(self.flash_colour(rows, 100.0 + self.m.FLASH_S + 0.1, state), {"blue"})

    def test_a_flash_outlives_a_refresh_inside_flash_s_and_ends_from_its_first_sighting(self):
        state = self.m.State()
        state.arrived(mail_snapshot(), {"alpha": 40}, 100.0)
        self.assertEqual(state.arrived(mail_snapshot(), {"alpha": 41}, 100.5), {("alpha", 41)})
        rows = [[("log", "blue ~flash:alpha:41")]]
        self.assertEqual(self.flash_colour(rows, 100.0 + self.m.FLASH_S - 0.1, state), {"amber", "bold"})
        self.assertEqual(self.flash_colour(rows, 100.0 + self.m.FLASH_S + 0.1, state), {"blue"})
        self.assertEqual(state.arrived(mail_snapshot(), {"alpha": 41}, 100.0 + self.m.FLASH_S + 0.1), set())

    def test_flash_holds_back_pulse_while_lit_and_pulse_resumes_after(self):
        state = self.m.State()
        state.arrived(mail_snapshot(), {"alpha": 40}, 0.0)
        rows = [[("●", "green ~pulse ~flash:alpha:41")]]
        steps = [k * self.m.PULSE_S / self.m.FPS for k in range(self.m.FPS)]
        for t in steps:
            self.assertEqual(self.flash_colour(rows, t, state), {"amber", "bold"}, t)
        after = math.ceil(self.m.FLASH_S / self.m.PULSE_S + 1) * self.m.PULSE_S
        self.assertEqual(self.flash_colour(rows, after, state), {"green"})
        shades = set().union(*(self.flash_colour(rows, after + t, state) for t in steps))
        self.assertEqual(shades, PULSE_SHADES)

    def ease_frames(self, before, after, state=None, t0=0.0):
        """Show `before` (its keys new), retarget to `after`, then the frames 0..EASE_FRAMES of `after`, one per
        1/FPS from t0."""
        state = self.m.State() if state is None else state
        state.retarget(self.m.cells(before))
        self.m.frame(before, t0, state)
        state.retarget(self.m.cells(after))
        return [self.m.frame(after, t0 + k / self.m.FPS, state) for k in range(self.m.EASE_FRAMES + 1)]

    def test_flash_and_ease_on_one_segment_ease_the_number_in_amber_bold(self):
        key = "~ease:focus:alpha/a:ctx:n"
        state = self.m.State()
        state.arrived(mail_snapshot(), {"alpha": 40}, 0.0)
        before = [[(" 20%", f"green bold {key}")]]
        after = [[(" 60%", f"salmon bold {key} ~flash:alpha:41")]]
        frames = self.ease_frames(before, after, state)
        self.assertEqual([gauge(f, 0, 4)[0] for f in frames], [" 20%", " 30%", " 40%", " 50%", " 60%"])
        for f in frames:
            self.assertEqual(set(gauge(f, 0, 4)[1]), {frozenset({"amber", "bold"})})
        settled = self.m.frame(after, self.m.FLASH_S + 1.0, state)
        self.assertEqual(gauge(settled, 0, 4), (" 60%", [frozenset({"salmon", "bold"})] * 4))

    def test_a_pips_gauge_eases_over_ease_frames_in_the_target_colours(self):
        key = f"~ease:{CTX_KEY}"
        before = [[("ctx ", None), ("▰", f"green {key}"), ("▱▱▱▱▱", f"faint {key}"), (" 9%", None)]]
        after = [[("ctx ", None), ("▰▰▰▰▰", f"salmon {key}"), ("▱", f"faint {key}"), (" 9%", None)]]
        frames = self.ease_frames(before, after)
        texts = [gauge(f, 4, 6)[0] for f in frames]
        self.assertEqual(texts, ["▰▱▱▱▱▱", "▰▰▱▱▱▱", "▰▰▰▱▱▱", "▰▰▰▰▱▱", "▰▰▰▰▰▱"])
        for f in frames:
            text, colours = gauge(f, 4, 6)
            for ch, colour in zip(text, colours):
                self.assertEqual(colour, {"salmon"} if ch == "▰" else {"faint"}, text)

    def test_an_eighth_bar_eases_over_ease_frames_in_the_target_colours(self):
        key = f"~ease:{CTX_KEY}"
        before = [[("▕", f"faint {key}"), ("▌", f"green {key}"), ("     ", f"faint {key}"), ("▏", f"faint {key}")]]
        after = [[("▕", f"faint {key}"), ("████▌", f"amber {key}"), (" ", f"faint {key}"), ("▏", f"faint {key}")]]
        frames = self.ease_frames(before, after)
        texts = [gauge(f, 0, 8)[0] for f in frames]
        self.assertEqual(texts, ["▕▌     ▏", "▕█▌    ▏", "▕██▌   ▏", "▕███▌  ▏", "▕████▌ ▏"])
        for f in frames:
            text, colours = gauge(f, 0, 8)
            self.assertEqual((colours[0], colours[-1]), ({"faint"}, {"faint"}), text)
            for ch, colour in zip(text[1:-1], colours[1:-1]):
                if ch != " ":
                    self.assertEqual(colour, {"amber"}, text)

    def test_a_number_eases_right_aligned_to_the_target_width_in_its_colour(self):
        key = f"~ease:{CTX_KEY}:n"
        before = [[("ctx ", None), ("5%", f"green {key}")]]
        after = [[("ctx ", None), (" 45%", f"salmon bold {key}")]]
        frames = self.ease_frames(before, after)
        self.assertEqual([gauge(f, 4, 4)[0] for f in frames], ["  5%", " 15%", " 25%", " 35%", " 45%"])
        for f in frames:
            self.assertEqual(len(grid(f)), 8)
            self.assertEqual(set(gauge(f, 4, 4)[1]), {frozenset({"salmon", "bold"})})

    def test_a_gauge_stays_at_its_target_after_ease_frames(self):
        key = f"~ease:{CTX_KEY}:n"
        state = self.m.State()
        frames = self.ease_frames([[(" 20%", f"green {key}")]], [[(" 60%", f"amber {key}")]], state)
        later = self.m.frame([[(" 60%", f"amber {key}")]], (self.m.EASE_FRAMES + 3) / self.m.FPS, state)
        self.assertEqual(gauge(frames[-1], 0, 4)[0], " 60%")
        self.assertEqual(gauge(later, 0, 4)[0], " 60%")

    def test_a_new_key_shows_its_target_at_once(self):
        state = self.m.State()
        state.retarget(self.m.cells([[("other", "green ~ease:builds:budget")]]))
        rows = [[("ctx ", None), ("▰▰▰▰▰", f"salmon ~ease:{CTX_KEY}"), ("▱", f"faint ~ease:{CTX_KEY}")]]
        state.retarget(self.m.cells(rows))
        self.assertEqual(grid(self.m.frame(rows, 0.0, state)), grid(self.m.strip(rows)))

    def test_frame_cells_draws_only_the_cells_whose_style_changed(self):
        rows = [[("ab ", None), ("●", "green ~pulse"), (" ", None), ("████", "teal ~sweep"), (" end", "dim")],
                [("agent ", None), ("━━━━━━", "blue ~flow"), (" ok", None)]]
        cells = self.m.cells(rows)
        state = self.m.State()
        state.retarget(cells)
        fps, t0 = self.m.FPS, 50.0
        screen = grid(self.m.frame(rows, t0, state))

        def draw(t):
            drawn = self.m.frame_cells(cells, t, state)
            before = dict(screen)
            for y, x, text, colour in drawn:
                for i, ch in enumerate(text):
                    screen[(y, x + i)] = (ch, words(colour))
            return {(y, x + i) for y, x, text, _ in drawn for i in range(len(text))}, before

        draw(t0 + 0.1 / fps)
        self.assertEqual(self.m.frame_cells(cells, t0 + 0.1 / fps, state), [])
        for k in range(1, 3 * fps):
            t = t0 + (k + 0.1) / fps
            drawn, before = draw(t)
            want = grid(self.m.frame(rows, t, self.m.State()))
            self.assertEqual(screen, want, f"frame {k}")
            self.assertEqual(drawn, changed(before, want), f"frame {k}")


class MotionAppTests(unittest.TestCase):
    """app.py: --no-motion, --pane passing it on, and the environment turning motion off."""

    def main(self, argv, env):
        """app.main(argv) under env (NO_MOTION and TERM unset unless given) with curses.wrapper faked; the
        wrapper's call."""
        from codeteam2.deck import app
        with patch.dict(os.environ, env), patch("curses.wrapper") as wrapper, \
                contextlib.redirect_stderr(io.StringIO()):
            for name in {"NO_MOTION", "TERM"} - env.keys():
                os.environ.pop(name, None)
            try:
                app.main(argv)
            except SystemExit as e:
                self.fail(f"deck {' '.join(argv)} exited at parse: {e}")
        return wrapper.call_args

    def motion_on(self, argv, env):
        call = self.main(argv, env)
        return call.kwargs.get("motion_on", call.args[-1])

    def test_no_motion_parses(self):
        from codeteam2.deck import app
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                self.assertTrue(app._parse(["--no-motion", "acme"]).no_motion)
                self.assertFalse(app._parse(["acme"]).no_motion)
            except SystemExit as e:
                self.fail(f"--no-motion did not parse: {e}")

    def test_pane_passes_no_motion_to_the_deck_it_runs(self):
        from codeteam2.deck import app
        from codeteam2.team import CODETEAM2
        fake = FakeDeckHerdr([{"workspace_id": "w1", "label": "tessa"}],
                             [{"pane_id": "p1", "workspace_id": "w1", "label": "tessa-orc"}])
        with patch("codeteam2.deck.app.Herdr", return_value=fake), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            try:
                self.assertEqual(app.main(["--pane", "--no-motion", "acme"]), 0)
            except SystemExit as e:
                self.fail(f"--pane --no-motion exited at parse: {e}")
        runs = [call for call in fake.calls if call[:2] == ("pane", "run")]
        self.assertEqual(len(runs), 1, fake.calls)
        command = runs[0][3]
        self.assertTrue(command.startswith(f"{CODETEAM2} deck "), command)
        self.assertIn("--no-motion", command.split())
        self.assertIn("acme", command.split())

    def test_motion_is_on_by_default(self):
        self.assertIs(self.motion_on([], {"TERM": "xterm-256color"}), True)

    def test_no_motion_flag_turns_motion_off(self):
        self.assertIs(self.motion_on(["--no-motion"], {"TERM": "xterm-256color"}), False)

    def test_no_motion_env_turns_motion_off(self):
        self.assertIs(self.motion_on([], {"NO_MOTION": "1", "TERM": "xterm-256color"}), False)

    def test_a_dumb_terminal_turns_motion_off(self):
        self.assertIs(self.motion_on([], {"TERM": "dumb"}), False)


class MotionIntegrationTests(unittest.TestCase):
    """The engine over render(motion=True): stripping gives today's render, frames move only tagged cells, and the
    frame loop's CPU cost is measured at 8 teams and 60 sessions."""

    @pytest.fixture
    def motion_capture(self, capsys):
        self.motion_capsys = capsys

    WIDTHS = (80, 120, 200)

    def setUp(self):
        from codeteam2.deck import motion, render
        self.m, self.r = motion, render
        self.fleet = fleet_snapshot()

    def snapshots(self):
        return [("render_snapshot", render_snapshot(), {("alpha", 9)}), ("fleet", self.fleet, {("team-0", 9)})]

    def test_stripping_the_motion_render_gives_the_still_render(self):
        for label, snap, flash in self.snapshots():
            for width in self.WIDTHS:
                for height in (None, 60):
                    with self.subTest(snapshot=label, width=width, height=height):
                        moving = self.r.render(snap, width, height=height, motion=True, flash=flash)
                        self.assertEqual(self.m.strip(moving), self.r.render(snap, width, height=height))

    def test_the_still_render_carries_no_tilde_word(self):
        for label, snap, _ in self.snapshots():
            for width in self.WIDTHS:
                for height in (None, 60):
                    for row in self.r.render(snap, width, height=height, motion=False):
                        for _, colour in row:
                            self.assertFalse(any(w.startswith("~") for w in words(colour)),
                                             f"{label} {width}x{height}: {colour!r}")

    def test_the_motion_render_tags_something(self):
        self.assertTrue(self.m.cells(self.r.render(self.fleet, 120, height=60, motion=True)))

    def test_two_frames_of_one_render_differ_only_in_tagged_cells(self):
        fps = self.m.FPS
        for label, snap, flash in self.snapshots():
            with self.subTest(snapshot=label):
                rows = self.r.render(snap, 120, height=60, motion=True, flash=flash)
                cells = self.m.cells(rows)
                state = self.m.State()
                state.retarget(cells)
                a, b = (grid(self.m.frame(rows, NOW + k / fps, state)) for k in (0.5, 2.5))
                self.assertLessEqual(changed(a, b), tagged_span(cells))
                if label == "fleet":
                    self.assertTrue(changed(a, b), "nothing moved at 60 working sessions")

    def frame_cost(self, width):
        """CPU seconds per frame of frame_cells plus a fake addstr per drawn cell: best of 5 batches of 60."""
        rows = self.r.render(self.fleet, width, height=60, motion=True)
        cells = self.m.cells(rows)
        state = self.m.State()
        state.retarget(cells)
        self.m.frame(rows, NOW, state)
        attrs = {word: 1 << i for i, word in enumerate([*self.r.PALETTE, "pulse2", "pulse3", "orange", "bold"])}
        screen, drawn, best, t = {}, 0, float("inf"), NOW

        def addstr(y, x, text, attr):
            screen[(y, x)] = (text, attr)

        for _ in range(5):
            start = time.process_time()
            for _ in range(60):
                t += 1 / self.m.FPS
                for y, x, text, colour in self.m.frame_cells(cells, t, state):
                    attr = 0
                    for word in (colour or "").split():
                        attr |= attrs.get(word, 0)
                    addstr(y, x, text, attr)
                    drawn += 1
            best = min(best, (time.process_time() - start) / 60)
        self.assertTrue(drawn, "no cell was drawn in 300 frames")
        return best

    @pytest.mark.usefixtures("motion_capture")
    def test_the_frame_loop_cpu_cost_is_measured(self):
        """Report the best mean frame CPU cost times FPS, without gating on elapsed CPU time."""
        for width in (120, 200):
            with self.subTest(width=width):
                share = self.frame_cost(width) * self.m.FPS
                with self.motion_capsys.disabled():
                    print(f"motion frame CPU {width}x60 at {self.m.FPS} fps: {share:.6%} of a core", flush=True)


if __name__ == "__main__":
    unittest.main()
