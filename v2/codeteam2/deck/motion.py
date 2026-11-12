"""Pure overlays for the last deck render; data collection and layout never run on a frame."""
from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import groupby
import math
import re

# Six frames per second make a moving head readable without spending the collection budget on layout.
FPS = 6
# A one-second cycle keeps the alive pulse perceptible without rapid flicker.
PULSE_S = 1.0
# Mail stays noticeable across a short refresh interval, but does not keep shouting after arrival.
FLASH_S = 2.0
# Four linear steps settle a gauge in two thirds of a second at six fps.
EASE_FRAMES = 4
# Two dark frames mark the sweep's restart, so even a one-cell job visibly cycles.
_HEAD_GAP_FRAMES = 2

Row = list[tuple[str, str | None]]
Cell = tuple[int, int, str, str | None, tuple]
_BLOCKS = "▏▎▍▌▋▊▉█"
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def enabled(no_motion: bool, environ: Mapping[str, str]) -> bool:
    return not (no_motion or environ.get("NO_MOTION") or environ.get("TERM") == "dumb")


def strip(rows: list[Row]) -> list[Row]:
    return [[(text, " ".join(w for w in (colour or "").split() if not w.startswith("~")) or None)
             for text, colour in row] for row in rows]


def cells(rows: list[Row]) -> list[Cell]:
    """Extract tagged segments in screen order; the deck's glyphs each occupy one terminal cell."""
    out = []
    for y, row in enumerate(rows):
        x = 0
        for text, colour in row:
            words = (colour or "").split()
            effects = []
            for word in words:
                if word.startswith("~"):
                    effect, _, key = word[1:].partition(":")
                    if effect == "flash":
                        team, _, mid = key.rpartition(":")
                        key = (team, int(mid))
                    effects.append((effect, key or None))
            if effects:
                out.append((y, x, text, " ".join(w for w in words if not w.startswith("~")) or None,
                            tuple(effects)))
            x += len(text)
    return out


@dataclass
class _Gauge:
    text: str
    colour: str | None
    target: float
    kind: str
    shown: float
    origin: float
    started: float | None = None
    painted: float | None = None
    styles: list = field(default_factory=list)

    def at(self, t: float) -> list:
        if self.shown != self.target:
            if self.started is None:
                self.started = t
            step = min(EASE_FRAMES, max(0, math.floor((t - self.started) * FPS + 1e-5)))
            self.shown = self.origin + (self.target - self.origin) * step / EASE_FRAMES
        if self.painted == self.shown:
            return self.styles
        self.painted = self.shown
        self.styles = self._styles()
        return self.styles

    def _styles(self) -> list:
        if self.kind == "number":
            match = _NUMBER.search(self.text)
            precision = len(match[0].partition(".")[2])
            number = f"{self.shown:.{precision}f}"
            text = (self.text[:match.start()].lstrip() + number + self.text[match.end():]).rjust(len(self.text))
            return [(ch, self.colour) for ch in text[-len(self.text):]]
        if self.kind == "pips":
            on = round(self.shown * len(self.text))
            return [("▰", self.colour)] * on + [("▱", "faint")] * (len(self.text) - on)
        steps = round(self.shown * (len(self.text) - 2) * 8)
        full, part = divmod(steps, 8)
        inner = ("█" * full + (_BLOCKS[part - 1] if part else "")).ljust(len(self.text) - 2)
        return ([("▕", "faint")] + [(ch, "faint" if ch == " " else self.colour) for ch in inner]
                + [("▏", "faint")])


def _reading(text: str) -> tuple[str, float] | None:
    if text and not set(text) - {"▰", "▱"}:
        return "pips", text.count("▰") / len(text)
    if text.startswith("▕") and text.endswith("▏") and len(text) > 2:
        return "bar", sum(_BLOCKS.index(ch) + 1 for ch in text[1:-1] if ch in _BLOCKS) / ((len(text) - 2) * 8)
    if match := _NUMBER.search(text):
        return "number", float(match[0])
    return None


def _gauge(parts: list[Cell], previous: _Gauge | None) -> _Gauge | None:
    text = "".join(p[2] for p in parts)
    reading = _reading(text)
    if reading is None:
        return None
    kind, value = reading
    colour = next((p[3] for p in parts if p[3] and "faint" not in p[3].split()), "faint")
    if previous is None or previous.kind != kind:
        return _Gauge(text, colour, value, kind, value, value)
    if previous.target == value:
        previous.text, previous.colour, previous.painted = text, colour, None
        return previous
    return _Gauge(text, colour, value, kind, previous.shown, previous.shown)


@dataclass
class _Span:
    y: int
    x: int
    text: str
    colour: str | None
    effects: dict
    gauge: _Gauge | None
    offset: int
    head_length: int = 0
    stamp: tuple | None = None
    shades: tuple = ()

    def __post_init__(self) -> None:
        self.head_length = len(self.text) if {"sweep", "flow"}.intersection(self.effects) else 0
        if "pulse" in self.effects:
            # Precompute the pulse's three styles once, not on every frame or cell.
            modifiers = [w for w in (self.colour or "").split() if w not in {"green", "pulse2", "pulse3"}]
            self.shades = tuple(" ".join([word, *modifiers]) for word in ("green", "pulse2", "pulse3"))

    def paint(self, t: float, tick: int, shade: int, flash_until: dict) -> list | None:
        flash = t < flash_until.get(self.effects.get("flash"), -math.inf)
        head = tick % (self.head_length + _HEAD_GAP_FRAMES) if self.head_length else -1
        styles = self.gauge.at(t)[self.offset:self.offset + len(self.text)] if self.gauge else None
        stamp = (flash, head, shade * bool(self.shades), self.gauge.shown if self.gauge else None)
        if stamp == self.stamp:
            return None
        self.stamp = stamp
        if styles is None:
            colour = self.shades[shade] if self.shades else self.colour
            styles = [(ch, colour) for ch in self.text]
        if 0 <= head < len(styles):
            styles[head] = (styles[head][0], "sky bold")
        if flash:
            styles = [(ch, "amber bold") for ch, _ in styles]
        return styles


class State:
    """Refresh-time targets, arrival deadlines and the styles actually shown on screen."""

    def __init__(self) -> None:
        self.flash_until = {}
        self._gauges = {}
        self._cells = None
        self._spans = []
        self._drawn = {}

    def arrived(self, snap: dict, prev_max_ids: dict, t: float) -> set[tuple[str, int]]:
        self.flash_until = {key: until for key, until in self.flash_until.items() if t < until}
        for team in snap.get("teams") or []:
            name = team.get("name")
            if name not in prev_max_ids:
                continue
            for message in (team.get("messages") or {}).get("last") or []:
                if message["id"] > prev_max_ids[name]:
                    self.flash_until.setdefault((name, message["id"]), t + FLASH_S)
        return set(self.flash_until)

    def retarget(self, tagged: list[Cell]) -> None:
        groups = {}
        for cell in tagged:
            key = dict(cell[4]).get("ease")
            if key:
                groups.setdefault(key, []).append(cell)
        self._gauges = {key: gauge for key, parts in groups.items()
                        if (gauge := _gauge(parts, self._gauges.get(key))) is not None}
        offsets = dict.fromkeys(groups, 0)
        self._spans = []
        for y, x, text, colour, effects in tagged:
            effects = dict(effects)
            key = effects.get("ease")
            self._spans.append(_Span(y, x, text, colour, effects, self._gauges.get(key), offsets.get(key, 0)))
            if key:
                offsets[key] += len(text)
        self._cells, self._drawn = tagged, {}


def frame_cells(tagged: list[Cell], t: float, state: State) -> list[tuple[int, int, str, str | None]]:
    """Restyle only overlays; compare per cell so moving heads do not repaint their whole segment."""
    if tagged is not state._cells and tagged != state._cells:
        state.retarget(tagged)
    tick = math.floor(t * FPS)
    shade = (0, 1, 2, 1)[min(3, int((t % PULSE_S) * 4 / PULSE_S))]
    out = []
    for span in state._spans:
        styles = span.paint(t, tick, shade, state.flash_until)
        if styles is None:
            continue
        for i, style in enumerate(styles):
            pos = (span.y, span.x + i)
            if state._drawn.get(pos) != style:
                state._drawn[pos] = style
                out.append((*pos, *style))
    return out


def frame(rows: list[Row], t: float, state: State) -> list[Row]:
    """Full draw from the last render, advancing the same easing clock as the small frame overlay."""
    tagged = cells(rows)
    frame_cells(tagged, t, state)
    out = []
    for y, row in enumerate(strip(rows)):
        x, drawn = 0, []
        for text, colour in row:
            for ch in text:
                drawn.append(state._drawn.get((y, x), (ch, colour)))
                x += 1
        # Full draws keep runs intact so still text does not become thousands of curses calls.
        out.append([("".join(ch for ch, _ in run), colour)
                    for colour, run in groupby(drawn, key=lambda style: style[1])])
    return out
