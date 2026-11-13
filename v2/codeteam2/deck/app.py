"""codeteam2 deck [teams...] [--json] [--pane] [--interval S] [--threshold K=V ...]

--json prints one snapshot and exits; --pane puts the live deck in herdr's `deck` workspace; with neither, the
live curses screen runs here. Motion overlays run between refreshes; --no-motion, non-empty NO_MOTION, or
TERM=dumb disables them. The deck reads only (collect, model and render do the work), apart from --pane,
which creates or reuses herdr's `deck` workspace and pane, the disk scanner's disk.json cache, and the error log
($CODETEAM_DECK_LOG, else ~/Library/Logs/codeteam-deck.log); this file wires them to the terminal.
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import time
import traceback
from pathlib import Path

from ..herdr import Herdr, HerdrError
from ..team import CODETEAM2, CT_HOME

DECK = "deck"
# Longest wait for a key: bounds how late a keypress is handled while the next refresh is not yet due.
POLL_S = 0.2


def _log(text):
    """Append an error to the deck's log: $CODETEAM_DECK_LOG, else ~/Library/Logs/codeteam-deck.log."""
    path = Path(os.environ.get("CODETEAM_DECK_LOG") or Path.home() / "Library" / "Logs" / "codeteam-deck.log")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(f"{dt.datetime.now().isoformat(timespec='seconds')} {text}\n")
    except OSError:
        pass


def _parse(argv):
    ap = argparse.ArgumentParser(prog="codeteam2 deck", description=__doc__.strip().splitlines()[0])
    ap.add_argument("teams", nargs="*", help="team products to show (default: every manifest in teams/, and each "
                                             "$CODETEAM_WORKSPACE/team-<x> that keeps its own in design/*/teams/<x>.toml)")
    ap.add_argument("--json", action="store_true", help="print one snapshot as JSON and exit")
    ap.add_argument("--pane", action="store_true", help="run the deck in herdr's `deck` workspace and pane")
    ap.add_argument("--no-motion", action="store_true", help="keep the live deck still")
    ap.add_argument("--interval", type=float, default=2.0, help="seconds between refreshes (default 2)")
    ap.add_argument("--threshold", action="append", default=[], metavar="K=V",
                    help="override an alert threshold, e.g. disk_red_gb=20 (repeatable)")
    return ap.parse_args(argv)


def _thresholds(pairs):
    """K=V pairs over model.THRESHOLDS, or None without any; an unknown key or a non-number exits with usage."""
    if not pairs:
        return None
    from . import model
    out = dict(model.THRESHOLDS)
    for pair in pairs:
        key, _, value = pair.partition("=")
        if key not in out:
            raise SystemExit(f"codeteam2 deck: unknown threshold {key!r} (known: {', '.join(out)})")
        try:
            out[key] = float(value)
        except ValueError:
            raise SystemExit(f"codeteam2 deck: threshold {key} needs a number, got {value!r}") from None
    return out


def _pane(teams, no_motion=False):
    """Reuse or create the `deck` workspace and its `deck` pane, then run the deck in it. Nothing else."""
    herdr = Herdr("codeteam")
    try:
        workspace = next((w for w in herdr.run("workspace", "list", timeout=10).get("workspaces", [])
                          if w.get("label") == DECK), None)
        if workspace is None:
            wid = herdr.workspace_create(str(CT_HOME), DECK)["workspace"]["workspace_id"]
        else:
            wid = workspace["workspace_id"]
        panes = herdr.run("pane", "list", "--workspace", wid, timeout=10).get("panes", [])
        running = next((p for p in panes if p.get("label") == DECK), None)
        if running:
            print(f"deck already running in pane {running['pane_id']}")
            return 0
        if not panes:
            print(f"herdr: workspace {wid} has no pane to run the deck in")
            return 1
        herdr.pane_rename(panes[0]["pane_id"], DECK)
        herdr.pane_run(panes[0]["pane_id"], " ".join([str(CODETEAM2), "deck", *teams,
                                                    *(["--no-motion"] if no_motion else [])]))
    except (HerdrError, subprocess.TimeoutExpired, OSError) as e:
        print(f"herdr: {e}")
        return 1
    return 0


def _next_filter(snap, current):
    """The team filter after `current`: None (all teams), then each team in turn, then None again."""
    names = [None] + [t.get("name") for t in snap.get("teams") or []]
    return names[(names.index(current) + 1) % len(names)] if current in names else None


def _handle(key, ui, snap, scanner):
    """Apply one key to the UI state (cursor, expanded, all_agents, team_filter); True when the key quits."""
    import curses
    from . import render
    ids = [sid for sid, _, _ in render.visible(snap, ui["team_filter"])]
    if key == ord("q"):
        return True
    if key in (curses.KEY_UP, ord("k")):
        ui["cursor"] = max(ui["cursor"] - 1, 0)
    elif key in (curses.KEY_DOWN, ord("j")):
        ui["cursor"] = min(ui["cursor"] + 1, max(len(ids) - 1, 0))
    elif key in (10, 13, curses.KEY_ENTER) and ids:
        ui["expanded"] ^= {ids[min(ui["cursor"], len(ids) - 1)]}
    elif key == ord("a"):
        ui["all_agents"] = not ui["all_agents"]
    elif key == ord("t"):
        ui["team_filter"], ui["cursor"] = _next_filter(snap, ui["team_filter"]), 0
    elif key == ord("d"):
        scanner.scan_now()
    return False


def _follow_teams(scanner, snap):
    """Point the disk scanner at the teams the last snapshot listed (their roots, and each one's v2/deck cache
    folder), and make sure its thread runs."""
    teams = [t for t in snap.get("teams") or [] if t.get("root") and t.get("home")]
    scanner.roots = {t["name"]: t["root"] for t in teams}
    scanner.cache_dir_for = {t["name"]: Path(t["home"]) / "v2" / "deck" for t in teams}.get
    scanner.start()


def _refresh(collect, names, cache, thresholds, alert_log, last, disk=None):
    """One collect() pass, as (snapshot, alerts kept for the session). A failure is logged and `last` (the
    previous pair) stays on screen."""
    try:
        snap = collect.collect(names, cache=cache, thresholds=thresholds, disk=disk)
        return snap, alert_log.update(snap.get("alerts") or [], snap.get("at") or time.time())
    except Exception:  # the screen outlives any one bad refresh
        _log(traceback.format_exc())
        return last


def _max_ids(snap: dict) -> dict:
    return {t["name"]: m["max_id"] for t in snap.get("teams") or []
            if (m := t.get("messages")) and m.get("max_id") is not None}


def _render_live(stdscr, snap: dict, alerts: list, ui: dict, state, now: float) -> list:
    """Layout happens only on a refresh or key; keep the tagged cells for the cheap frame path."""
    from . import motion, render
    height, width = stdscr.getmaxyx()
    if state is None:
        render.draw(stdscr, render.render(snap, width, height=height, alert_log=alerts, **ui))
        return []
    flash = {key for key, until in state.flash_until.items() if now < until}
    rows = render.render(snap, width, height=height, alert_log=alerts, motion=True, flash=flash, **ui)
    tagged = motion.cells(rows)
    state.retarget(tagged)
    render.draw(stdscr, motion.frame(rows, now, state))
    return tagged


def _draw_frame(stdscr, tagged: list, now: float, state, attrs: dict) -> None:
    """Do not erase: each update is one changed overlay cell, clipped like render._placements."""
    from . import motion
    height, width = stdscr.getmaxyx()
    for y, x, text, colour in motion.frame_cells(tagged, now, state):
        if y >= height or x >= width - (y == height - 1):
            continue
        attr = 0
        for word in (colour or "").split():
            attr |= attrs[word]
        stdscr.addstr(y, x, text, attr)
    stdscr.refresh()


def _live(stdscr, names, interval, thresholds, motion_on):
    import curses
    from . import collect, model, motion, render
    cache, alert_log = collect.Cache(), model.AlertLog()
    scanner = collect.DiskScanner({})
    ui = {"cursor": 0, "expanded": set(), "all_agents": False, "team_filter": None}
    state = motion.State() if motion_on else None
    attrs = render._colour_attrs(curses) if motion_on else {}
    frame_step = 1 / motion.FPS if motion_on else float("inf")
    tagged, frame_due = [], float("inf")
    curses.curs_set(0)
    (snap, alerts), due, redraw = ({}, []), 0.0, True
    while True:
        if time.time() >= due:
            previous = _max_ids(snap)
            snap, alerts = _refresh(collect, names, cache, thresholds, alert_log, (snap, alerts),
                                     scanner.result())
            _follow_teams(scanner, snap)
            if state is not None:
                state.arrived(snap, previous, time.time())
            due, redraw = time.time() + interval, True
        now = time.time()
        if redraw:
            tagged = _render_live(stdscr, snap, alerts, ui, state, now)
            frame_due = now + frame_step
        elif now >= frame_due:
            _draw_frame(stdscr, tagged, now, state, attrs)
            frame_due = now + frame_step
        stdscr.timeout(int(max(min(due - time.time(), frame_due - time.time(), POLL_S), 0.01) * 1000))
        key = stdscr.getch()
        redraw = key != -1
        if redraw and _handle(key, ui, snap, scanner):
            return


def main(argv):
    args = _parse(argv)
    if args.pane:
        return _pane(args.teams, args.no_motion)
    thresholds = _thresholds(args.threshold)
    if args.json:
        from . import collect
        print(json.dumps(collect.collect(args.teams, thresholds=thresholds)))
        return 0
    import curses
    from . import motion
    curses.wrapper(_live, args.teams, args.interval, thresholds, motion.enabled(args.no_motion, os.environ))
    return 0
