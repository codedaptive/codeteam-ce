"""Flightdeck-style boxes and gauges from a deck snapshot, without source reads.

render() returns rows of (text, colour-word) segments. At 120 columns the cursor's team scrolls beside a
docked right column; narrower screens stack them. Some rows use _fit to budget required and optional fields,
while mail, flags and worktree parts use _wrap. With a height, header, fleet, alerts and keys are pinned when
space permits; the middle windows team rows, trims lists with `+n more`, and fits dock panels to the room.
BUILDS and log stay whole or absent; DISK drops detail before its team rows. Missing readings generally show `?`.
With motion on, animated segments carry extra colour words starting with `~` (pulse, sweep, flow, flash, ease);
the texts are the same either way, and draw() ignores those words.
"""
import datetime as dt
import functools
import math

SPARK = "▁▂▃▄▅▆▇█"
# The partial cell of an eighth-block bar, one to seven eighths.
EIGHTHS = "▏▎▍▌▋▊▉"
# Display thresholds match model's defaults; threshold overrides affect alerts, not these gauges.
HEARTBEAT_RED_S = 60
DISK_RED_GB = 50
# Colour a worktree's four build-output parts above the model's default 10 GB alert threshold.
BUILD_RED_GB = 10
# Leave space for the dashboard when a fixed-height screen has many alerts.
ALERT_ROWS = 6
BUILD_PARTS = ("cargo-target", "target", ".build", "node_modules", ".codegraph", "scratchpad")
RED_KINDS = ("blocked", "held", "heartbeat", "stalled", "child_finished", "disk_low")
ROLE = {"orc": "coral", "designer": "purple", "guard": "teal", "lane": "blue"}
KIND = {"REQUEST": "amber", "ANSWER": "blue", "DONE": "green", "PUSHED": "green", "READY": "teal",
        "NOTE": "purple", "BUG": "salmon", "RULING": "coral"}
# Xterm 256-colour indices approximate Flightdeck's pastel roles and muted borders.
PALETTE = {"coral": 173, "purple": 183, "teal": 80, "blue": 111, "green": 114, "sky": 117,
           "amber": 221, "salmon": 210, "dim": 243, "edge": 241, "faint": 238, "orange": 215,
           "pulse2": 72, "pulse3": 65}
# Name caps fit this queued-job example's required fields into the dock's 49-cell body:
# `#21 ` + team 8 + ` · ` + session 10 + `  held warm` + `  wait 23h59m` = 49. A job's worktree tail is optional
# and gets the same 10 as the session, so a wider box shows it before a narrow one shows nothing.
TEAM_CAP, SESSION_CAP, JOB_TAIL_CAP = 8, 10, 10
# A DISK worktree tail of 14 keeps its row's lead (`  <tail> 123.4G  `, 25 cells) to half the dock's 49-cell body,
# so the first build part (`node_modules 123.4G`, 19) still shares it; the rest wrap under it.
PATH_CAP = 14
# Halted and alert rows give a team name 10 cells, as the mock's team column.
NAME_CAP = 10
# A session row's cells other than its name and badge: cursor 1, glyph 2, age 8, context bar 8 (6 cells between
# two edges), percent 4, cost 8.
SESSION_FIXED = 31
# The name column is the spec's 20-wide name plus a gap; it gives way to badges down to a 12-cell name,
# which leaves room for 11 characters before the `…`.
NAME_COLUMN, NAME_FLOOR = 21, 12
# A title gives way to its box's caption down to this many cells, enough to recognise the box.
TITLE_FLOOR = 8
# Under 120 columns the team window keeps the cursor row and its neighbours however tall the focus box is.
TEAM_RESERVE = 3
Row = list[tuple[str, str | None]]


def _num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else None


def _c(text, colour=None):
    return [(str(text), colour)]


def _dur(s):
    s = _num(s)
    if s is None:
        return "?"
    s = max(int(s), 0)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h{s % 3600 // 60:02d}m"
    return f"{s // 86400}d{s % 86400 // 3600}h"


def _timer(s):
    if _num(s) is None:
        return "?"
    s = max(0, int(s))
    return f"{s // 60}:{s % 60:02d}" if s < 3600 else f"{s // 3600}h{s % 3600 // 60:02d}"


def _clock(ts, secs=False):
    """Local time from an epoch or ISO timestamp; `?` for a failed reading."""
    try:
        when = dt.datetime.fromtimestamp(ts) if _num(ts) is not None else dt.datetime.fromisoformat(ts)
    except (TypeError, ValueError, OverflowError, OSError):
        return "?"
    return when.astimezone().strftime("%H:%M:%S" if secs else "%H:%M")


def _count(x):
    return "?" if _num(x) is None else (f"{x / 1000:.1f}k" if x >= 1000 else f"{x:.0f}")


def _g(x):
    return "?" if _num(x) is None else f"{x:g}"


def _usd(x):
    return "$?" if _num(x) is None else f"${x:.2f}"


def _gb(x):
    return "?" if _num(x) is None else f"{x:.1f}G"


def _dicts(items):
    return [x for x in items if isinstance(x, dict)] if isinstance(items, list) else []


def _mapping(x):
    return x if isinstance(x, dict) else {}


def sparkline(counts: list) -> str:
    """One glyph per count, scaled to the largest; zero and non-numbers are dots."""
    nums = [_num(n) or 0 for n in counts]
    top = max(nums, default=0)
    return "".join("·" if n <= 0 else SPARK[min(7, int(n / top * 7.999))] for n in nums)


def _len(row):
    return sum(len(text) for text, _ in row)


def _clip(row, width):
    out, left = [], max(0, width)
    for text, colour in row:
        if left <= 0:
            break
        out.append((text[:left], colour))
        left -= len(text)
    return out


def _cut(row, width):
    """The row whole when it fits, else cut to width with a closing `…`."""
    if _len(row) <= width:
        return row
    return _clip(row, width - 1) + _c("…", "dim") if width > 0 else []


def _pad(row, width):
    if width <= 0:
        return []
    row = _cut(row, width)
    return row + _c(" " * (width - _len(row)))


def _column(row, width):
    """A fixed column that always leaves a one-cell gap before the next field."""
    return _pad(_cut(row, width - 1), width)


def _cap(text, n):
    text = str(text)
    return text if len(text) <= n else text[:n - 1] + "…"


def _tail(path, n=40):
    path = str(path or "?").rstrip("/").rsplit("/", 1)[-1]
    return path if len(path) <= n else "…" + path[-(n - 1):]


def _fit(fields, width):
    """Budget fields against width in display order. A field is (row, rank): rank 0 is required and always
    kept; the others are tried lowest rank first, each kept whole or left out, and a field after a left-out one is
    still tried. Required fields that alone overflow are cut at the row's end by the caller's padding.
    Selected rows use _wrap instead to put required parts on continuation lines."""
    used = sum(_len(row) for row, rank in fields if not rank)
    kept = [not rank for _, rank in fields]
    for i in sorted((i for i, (_, rank) in enumerate(fields) if rank), key=lambda i: fields[i][1]):
        if used + _len(fields[i][0]) <= width:
            kept[i], used = True, used + _len(fields[i][0])
    return [segment for (row, _), keep in zip(fields, kept) if keep for segment in row]


def _centre(row, width):
    return _pad(_c(" " * max(0, (width - _len(row)) // 2)) + row, width)


def _box(title, rows, width, colour="edge", right=None):
    # Corners, the spaces around title and caption and one rule cell take 9 columns (7 without a caption).
    # The caption carries the box's state, so the title gives way first, down to TITLE_FLOOR cells;
    # only then is the caption cut.
    if right:
        title = _cut(title, max(min(_len(title), TITLE_FLOOR), width - 9 - _len(right)))
        right = _cut(right, width - 9 - _len(title))
    else:
        title = _cut(title, width - 7)
    tail = _c(" ") + right + _c(" ") if right else []
    head = _c("╭─ ", colour) + title + _c(" ")
    top = head + _c("─" * max(0, width - _len(head) - _len(tail) - 2), colour) + tail + _c("─╮", colour)
    body = [_c("│ ", colour) + _pad(row, width - 4) + _c(" │", colour) for row in rows]
    return [top] + body + [_c("╰" + "─" * max(0, width - 2) + "╯", colour)]


def _tag(row, word):
    """row with word added after each non-empty segment's colour; word None leaves the row as it is. Empty
    segments (a fitted row's zero-width padding) stay untagged, since they sit at the next field's column."""
    if not word:
        return row
    return [(text, (f"{colour} {word}" if colour else word) if text else colour) for text, colour in row]


def _ease(motion, key):
    return f"~ease:{key}" if motion else None


def _pips(value, maximum, cells, colour, tag=None):
    # Lanes only: a count against its cap as segment pips scaled to cells, six in a fleet cell and ten in a team
    # box. An unreadable gauge is `?` and carries no tag, since there is no value to ease.
    if _num(value) is None or _num(maximum) is None or maximum <= 0:
        return _c("?", "amber")
    on = 0 if value <= 0 else max(1, min(cells, round(value / maximum * cells)))
    return _tag(_c("▰" * on, colour) + _c("▱" * (cells - on), "faint"), tag)


def _bar(value, maximum, cells, colour, tag=None):
    """`▕` + cells eighth-block cells + `▏`: cells * 8 steps, any value above zero at least one eighth. The fill is
    in colour, the spaces and edges faint; `?` amber (untagged) when unreadable."""
    if _num(value) is None or _num(maximum) is None or maximum <= 0:
        return _c("?", "amber")
    full, part = divmod(0 if value <= 0 else max(1, min(cells * 8, round(value / maximum * cells * 8))), 8)
    fill = "█" * full + (EIGHTHS[part - 1] if part else "")
    return _tag(_c("▕", "faint") + _c(fill, colour) + _c(" " * (cells - len(fill)) + "▏", "faint"), tag)


def _teams(snap, team_filter):
    return [t for t in snap.get("teams") or [] if team_filter in (None, t.get("name"))]


def visible(snap: dict, team_filter: str | None = None) -> list:
    """(id, team, session) in snapshot order for the cursor, excluding HALTED teams so it cannot select
    a session without a team box."""
    return [(f"{t.get('name')}/{s.get('key')}", t, s) for t in _teams(snap, team_filter)
            if t.get("state") != "HALTED" for s in t.get("sessions") or []]


def _listed(items, width, gap="   "):
    """Items in order, each whole or left out; every item after the first carries a leading gap."""
    return _fit([((_c(gap, "dim") if i else []) + item, i + 1) for i, item in enumerate(items)], width)


def _header(snap, teams, alerts, width, team_filter):
    up = sum(t.get("state") == "up" for t in teams)
    lanes = sum(_num(t.get("lanes_running")) or 0 for t in teams)
    dot = _c(" · ", "dim")
    # The counts, the filter and the source errors are what the reader acts on; the clock gives way, and
    # LANES WORKING before it, since the fleet box shows every team's lanes.
    fields = [(_c("CODETEAM DECK", "bold"), 0), (dot + _c(f"{up} UP", "green bold"), 0),
              (dot + _c(f"{len(teams) - up} HALTED", "salmon bold"), 0),
              (dot + _c(f"{lanes:g} LANES", "blue bold") + _c(" WORKING", "bold"), 2),
              (dot + _c(f"▲ {len(alerts)} ALERTS", "amber bold"), 0), (_c(f" · {_clock(snap.get('at'))}", "dim"), 1)]
    if team_filter:
        fields.append((_c(f" · team {team_filter}", "blue"), 0))
    if snap.get("errors"):
        fields.append((_c(f" · {len(snap['errors'])} source errors", "salmon"), 0))
    legend = [_c(f"■ {role}", ROLE.get(role, "dim")) for role in ("orc", "designer", "guard", "lane", "crew")]
    legend += [_c(f"{glyph} {word}", colour) for glyph, word, colour in (
        ("●", "working", "green"), ("◐", "between turns", "sky"), ("○", "idle", "dim"), ("✓", "done", "green"),
        ("■", "blocked", "salmon"))]
    return [_centre(_fit(fields, width), width), _centre(_listed(legend, width), width), _c(" " * width)]


def _free(snap):
    free = _num(_mapping(snap.get("volume")).get("free_gb"))
    return _c(f"{'?' if free is None else f'{free:.0f}G'} free", "amber" if free is None else
              "salmon" if free < DISK_RED_GB else "dim")


def _team_state(t):
    return "halted" if t.get("state") == "HALTED" else t.get("state") or "?"


def _lanes(t, cells, tag):
    lanes, cap = _num(t.get("lanes_running")), _num(t.get("cap"))
    colour = "salmon" if lanes is not None and cap is not None and lanes > cap else "blue"
    return _pips(lanes, cap, cells, colour, tag) + _c(f" {_g(lanes)}/{_g(cap)}", colour if colour == "salmon" else "dim")


def _mail_counts(cell, waiting_key="waiting", broadcasts_key="broadcasts"):
    waiting, broadcasts = _num(cell.get(waiting_key)), _num(cell.get(broadcasts_key))
    return (waiting - broadcasts if waiting is not None and broadcasts is not None else waiting), broadcasts


def _mail_age(mail):
    # Missing broadcast counts identify snapshots whose ages still cover every undelivered message.
    if _num(mail.get("broadcasts")) is None:
        return mail.get("oldest_waiting_s")
    return mail.get("oldest_mail_s", mail.get("oldest_waiting_s"))


def _fleet_mail(t, width):
    mail, broadcasts = _mail_counts(t, "mail_waiting", "broadcasts_waiting")
    up = t.get("state") == "up"
    waiting = _c(f"✉{_g(mail)}", "amber" if mail is None or mail > 0 else "faint") if up or mail else []
    ring = _c(f"{' ' if waiting else ''}◎{_g(broadcasts)}", "dim") if broadcasts and broadcasts > 0 else []
    if not up:
        return _fit([(waiting, 0), (ring, 0)], width) if waiting or ring else _c("loop off", "faint")
    return _fit([(waiting, 0), (ring, 0), (_c(f" {_g(t.get('msgs_last_hour'))}/h", "dim"), 0)], width)


def _fleet(teams, snap, width, motion):
    order = sorted(teams, key=lambda t: (t.get("state") != "up", -(_num(t.get("running")) or 0)
                                        if t.get("state") == "up" else 0))
    inner = max(1, width - 4)
    cell_width = max(14, inner // max(1, len(order)))
    per_row = max(1, inner // cell_width)
    cells = []
    for t in order:
        up = t.get("state") == "up"
        name = _c("● " if up else "■ ", "green" if up else "salmon") + _c(t.get("name") or "?", "bold" if up else "dim")
        lanes = _lanes(t, 6, _ease(motion, f"lanes:{t.get('name')}:fleet")) if up else _c(_team_state(t), "salmon")
        cells.append([_column(row, min(cell_width, inner))
                      for row in (name, lanes, _fleet_mail(t, min(cell_width, inner) - 1))])
    rows = []
    for start in range(0, len(cells), per_row):
        rows += [sum((cell[i] for cell in cells[start:start + per_row]), []) for i in range(3)]
    late = [str(t.get("name") or "?") for t in teams if t.get("state") == "up"
            and (_num(t.get("heartbeat_age_s")) or 0) > HEARTBEAT_RED_S]
    right = _free(snap) + _c(" · loops ", "dim") + _c(", ".join(late) if late else "all beating", "salmon" if late else "green")
    return _box(_c("FLEET", "bold") + _c(f" · {len(teams)} team{'s' if len(teams) != 1 else ''}", "dim"), rows, width, right=right)


def _state(s, now):
    h, f = s.get("herdr") or {}, s.get("flags") or {}
    status = h.get("status") or "?"
    since = _num(h.get("since"))
    age = _dur(now - since) if since is not None else "?"
    if status == "blocked":
        return "■", "blocked", "salmon", _dur(f.get("blocked_for_s")) if _num(f.get("blocked_for_s")) is not None else age
    if f.get("between_turns"):
        return "◐", "between", "sky", age
    glyph, word, colour = {"working": ("●", "working", "green"), "idle": ("○", "idle", "dim"),
                           "done": ("✓", "done", "green"), "absent": ("·", "ended", "faint")}.get(status, ("?", "?", "amber"))
    return glyph, word, colour, age


def _flags(s):
    f = s.get("flags") or {}
    parts = []
    if f.get("waiting_on_finished_child"):
        parts.append(_c("child done", "salmon bold"))
    if f.get("blocked") or (s.get("herdr") or {}).get("status") == "blocked":
        parts.append(_c(f"blocked {_dur(f.get('blocked_for_s'))}", "salmon bold"))
    if s.get("draft_since") is not None or f.get("typing"):
        parts.append(_c("typing", "amber"))
    if s.get("api_error") or f.get("api_error"):
        parts.append(_c("api error", "amber"))
    if _num(s.get("idle_exit_in_s")) is not None:
        parts.append(_c(f"exit {_dur(s.get('idle_exit_in_s'))}", "faint"))
    return parts


def _waiting_badge(mail):
    waiting, broadcasts = _mail_counts(mail)
    if waiting and waiting > 0:
        return _c(f" ✉{_g(waiting)} {_dur(_mail_age(mail))}", "amber")
    if broadcasts and broadcasts > 0:
        return _c(f" ◎{_g(broadcasts)}", "dim")
    return []


def _badge(s):
    """The first badge that applies, with its leading gap; ` child done ` is drawn as a chip."""
    f, m = s.get("flags") or {}, s.get("mail") or {}
    if f.get("waiting_on_finished_child"):
        return _c(" child done ", "salmon bold")
    if f.get("blocked") or (s.get("herdr") or {}).get("status") == "blocked":
        return _c(" blocked", "salmon bold")
    if f.get("held") or m.get("held"):
        return _c(f" held {_g(m.get('held'))}", "salmon")
    if s.get("draft_since") is not None or f.get("typing"):
        return _c(" typing", "amber")
    if s.get("api_error") or f.get("api_error"):
        return _c(" api error", "amber")
    badge = _waiting_badge(m)
    if badge:
        return badge
    if _num(s.get("idle_exit_in_s")) is not None:
        return _c(f" exit {_dur(s.get('idle_exit_in_s'))}", "faint")
    return []


def _ctx_colour(p):
    """Context heats up at 30%, 40% and 50% to make rising fill visible (SPEC-deck-motion §B1);
    an unknown fill is amber."""
    if p is None:
        return "amber"
    return "green" if p < 30 else "amber" if p < 40 else "orange" if p < 50 else "salmon"


def _pulse(word, motion):
    return "~pulse" if motion and word == "working" else None


def _flash_ids(t, flash):
    """{match: newest id} over the team's logged messages that are in flash. A message with a `target` (the session
    key its recipient resolved to; the recipient itself can be `all` or a comma list) matches ("key", target); one
    without matches ("any", recipient), a session's name or key. A target naming no session matches no row."""
    ids = {}
    for x in _dicts(_mapping(t.get("messages")).get("last")) if flash else ():
        match, mid = ("key", x["target"]) if "target" in x else ("any", x.get("recipient")), x.get("id")
        if match[1] and (t.get("name"), mid) in flash:
            ids[match] = max(ids.get(match, mid), mid)
    return ids


def _session_row(s, now, current, name_width, badge, gauge, motion):
    """gauge is the row's ease key stem, `row:<team>/<key>:ctx`."""
    glyph, word, colour, age = _state(s, now)
    pct = _num((s.get("context") or {}).get("used_pct"))
    name = _c(s.get("name") or s.get("key") or "?", ROLE.get(s.get("role"), "dim") + (" bold" if current else ""))
    percent = _c(f"{_g(pct):>3}%", _ctx_colour(pct))
    return (_c("▸" if current else " ", "coral bold") + _tag(_c(glyph + " ", colour), _pulse(word, motion))
            + _column(name, name_width) + _c(f"{age:>6}  ", "dim")
            + _bar(pct, 100, 6, _ctx_colour(pct), _ease(motion, gauge))
            + (_tag(percent, _ease(motion, gauge + ":n")) if pct is not None else percent)
            + _c(f"{_usd((s.get('cost') or {}).get('session_usd')):>8}") + badge)


def _team_box(t, now, current, width, motion, flash):
    ss, messages = t.get("sessions") or [], t.get("messages")
    name = t.get("name") or "?"
    costs = [_num((s.get("cost") or {}).get("session_usd")) for s in ss]
    known = [cost for cost in costs if cost is not None]
    mail, broadcasts = _mail_counts(t, "mail_waiting", "broadcasts_waiting")
    rows = [_fit([(_lanes(t, 10, _ease(motion, f"lanes:{name}:box")) + _c(" lanes  ·  ", "dim"), 0),
                  (_c(f"✉ {_g(mail)}", "amber" if mail else "dim"), 0),
                  (_c(f"  ·  ◎ {_g(broadcasts)}", "dim") if broadcasts and broadcasts > 0 else [], 0),
                  (_c("  ·  ", "faint") + _c(f"{_usd(sum(known) if known else None)} today", "coral"), 0)], width - 4)]
    if isinstance(messages, dict):
        spark = sparkline(messages.get("hourly") or [])
        rows.append(_c("24h ", "dim") + [(glyph, "faint" if glyph == "·" else "blue") for glyph in spark]
                    + _c(f"  {_g(messages.get('last_hour'))}/h", "bold"))
    else:
        rows.append(_c("24h ?", "amber"))
    badges = [_badge(s) for s in ss]
    # One name column per box keeps the ages aligned; it narrows so the widest badge shows whole.
    widest = max(map(_len, badges), default=0)
    name_width = max(NAME_FLOOR + 1, min(NAME_COLUMN, width - 4 - SESSION_FIXED - widest))
    flashed = _flash_ids(t, flash)
    for s, badge in zip(ss, badges):
        row = _session_row(s, now, s is current, name_width, badge, f"row:{name}/{s.get('key')}:ctx", motion)
        matches = (("key", s.get("key")), ("any", s.get("name")), ("any", s.get("key")))
        ids = [flashed[m] for m in matches if m in flashed]
        # Padded here whether it flashes or not: the flash then covers the row's closing `…`, and motion on and
        # off keep the same segments.
        rows.append(_tag(_pad(row, width - 4), f"~flash:{name}:{max(ids)}" if ids else None))
    beat = _num(t.get("heartbeat_age_s"))
    right = (_c("● up", "green") + _c(" · loop ", "dim")
             + _c(_dur(beat), "amber" if beat is None else "salmon" if beat > HEARTBEAT_RED_S else "dim")) if t.get("state") == "up" else _c(_team_state(t), "salmon")
    title = _c(name, "bold") + _c(f" · {len(ss)} session{'s' if len(ss) != 1 else ''}", "dim")
    return _box(title, rows, width, "blue" if any(s is current for s in ss) else "edge", right)


def _halted(teams, width):
    rows = []
    for t in teams:
        if t.get("state") == "up":
            continue
        beat = _num(t.get("heartbeat_age_s"))
        mail, broadcasts = _mail_counts(t, "mail_waiting", "broadcasts_waiting")
        row = (_c("■ ", "salmon") + _column(_c(t.get("name") or "?", "dim"), NAME_CAP + 1) + _c(_team_state(t), "salmon")
               + _c(f" · loop off {_dur(beat) if beat is not None else 'never started'}", "faint"))
        rows.append(_fit([(row, 0), (_c(f" · ✉ {_g(mail)} waiting", "amber") if mail and mail > 0 else [], 0),
                          (_c(f" · ◎ {_g(broadcasts)}", "dim") if broadcasts and broadcasts > 0 else [], 0)], width - 4))
    return _box(_c("halted", "dim bold"), rows, width) if rows else []


def _model(s):
    model = str(s.get("model") or "?").removeprefix("claude-")
    if model.startswith("opus-"):
        return "Opus " + model[5:].replace("-", ".")
    if model.startswith("sonnet-"):
        return "Sonnet " + model[7:].replace("-", ".")
    return model[:12]


def _focus_context(s, gauge, motion):
    """gauge is the box's ease key stem, `focus:<team>/<key>:ctx`."""
    ctx = s.get("context") or {}
    pct, window = _num(ctx.get("used_pct")), _num(ctx.get("window"))
    tokens = "?" if pct is None or window is None else f"{window * pct / 100000:.0f}"
    win = "?" if window is None else f"{window / 1e6:.1f}"
    percent = _c(f" {_g(pct)}%", f"{_ctx_colour(pct)} bold")
    return (_c("ctx ", "dim") + _bar(pct, 100, 10, _ctx_colour(pct), _ease(motion, gauge))
            + (_tag(percent, _ease(motion, gauge + ":n")) if pct is not None else percent)
            + _c(f" {tokens}k/{win}M  ⟲{_g(ctx.get('compactions'))}{'+' if ctx.get('compactions_partial') else ''}", "dim"))


def _cache(s):
    cache = s.get("cache") or {}
    if cache.get("warm") is None:
        return _c("cache ?", "amber")
    if not cache.get("warm"):
        return _c("cache ◇ cold", "dim")
    hit = _num(cache.get("hit_ratio"))
    return (_c("cache ", "dim") + _c("◆ warm", "purple")
            + _c(f" {_dur(cache.get('expires_in_s'))} left · hit {'?' if hit is None else f'{hit * 100:.0f}'}%", "dim"))


def _tools(s, width):
    """`tools read → edit → bash`: the trace's names (else the recent tools'), oldest first; the oldest give way
    only as far as width needs, behind `… → `."""
    recent = s.get("recent") or {}
    trace = recent.get("trace")
    names = [str(n).lower() for n in trace] if isinstance(trace, list) else [
        str(t.get("name") or "?").lower() for t in _dicts(recent.get("tools"))]
    if not names:
        return _c("tools –", "dim")
    lead = "tools "
    while len(names) > 1 and len(lead) + len(" → ".join(names)) > width:
        lead, names = "tools … → ", names[1:]
    return _c(lead, "dim") + _c(" → ".join(names))


def _turns(s, width):
    """`turns ▁▂▃▅↓▁▃  ~24 turns left`: output tokens per turn scaled to the largest shown, `↓` for a compaction,
    the newest kept when width is short; turns left coloured by how few remain, left out without an estimate."""
    turns, left = s.get("turns"), _num(s.get("turns_left"))
    tail = [] if left is None else _c(f"  ~{left:.0f} turns left", "green" if left > 30 else "amber" if left > 15
                                      else "orange" if left > 5 else "salmon")
    if not isinstance(turns, list):
        return _c("turns ", "dim") + _c("?", "amber") + tail
    shown = [x for x in turns if _num(x) is not None or isinstance(x, dict) and x.get("compacted")]
    shown = shown[-max(1, width - 6 - _len(tail)):]
    if not shown:
        return _c("turns –", "dim") + tail
    top = max((_num(x) or 0 for x in shown), default=0)
    glyphs = [("↓", "sky") if isinstance(x, dict) else
              (SPARK[min(7, int(x / top * 7.999)) if top > 0 and x > 0 else 0], "blue") for x in shown]
    return _c("turns ", "dim") + glyphs + tail


def _wrap(prefix, parts, width, separator=" "):
    """The field layout's wrap mode, for rows whose parts are all required: each part whole, in order, after the
    prefix; a part that does not fit starts a continuation row indented past the prefix, the indent shrinking
    down to 2 so the widest part fits. A part wider than width - 2 is the one case cut with `…`."""
    indent = max(2, min(_len(prefix), width - max(map(_len, parts), default=0)))
    rows, row, placed = [], list(prefix), False
    for part in parts:
        gap = _c(separator, "dim") if placed else []
        if _len(row) + _len(gap) + _len(part) > width and (placed or _len(prefix) > indent):
            rows.append(row)
            row, gap = _c(" " * indent), []
        row += gap + _cut(part, width - _len(row))
        placed = True
    return rows + [row]


def _more(rows, room, keep=0):
    """Return all rows if they fit; otherwise replace the last shown row with `+n more` (dim).
    Return [] when a truncated list cannot hold the keep leading rows and that line."""
    if len(rows) <= room:
        return rows
    if room <= keep:
        return []
    return rows[:room - 1] + [_c(f"+{len(rows) - room + 1} more", "dim")]


def _mail(s, width):
    mail = s.get("mail") or {}
    waiting, broadcasts = _mail_counts(mail)
    oldest = _mail_age(mail)
    parts = [_c(f"✉ {_g(waiting)}", "amber" if waiting else "dim") + _c(" waiting", "dim")]
    if broadcasts is not None:
        parts.append(_c(f"◎ {_g(broadcasts)} broadcasts", "dim"))
    parts += [_c(f"↓{_g(mail.get('delivered_today'))} today", "dim"),
              _c(f"oldest {_dur(oldest) if oldest is not None else '–'}", "dim")]
    if mail.get("held"):
        parts.append(_c(f"held {_g(mail.get('held'))}", "salmon bold"))
    return _wrap(_c("mail ", "dim"), parts, width, " · ")


def _detail(s):
    recent = s.get("recent") or {}
    rows = [_c(f"tool {t.get('name') or '?'} {t.get('summary') or ''}", "dim") for t in _dicts(recent.get("tools"))[:5]]
    for m in _dicts(recent.get("messages"))[:5]:
        rows.append(_c(f"msg {'←' if m.get('dir') == 'in' else '→'} {_clock(m.get('ts'))} {m.get('peer') or '?'} "
                       f"{m.get('kind') or '?'} {m.get('text') or ''}", "dim"))
    return rows or [_c("nothing recent", "dim")]


def _focus(s, t, now, width, expanded, room, motion):
    """The cursor's session in one box of at most room rows, or [] when its facts alone do not fit; the
    expanded detail gives way first, its last kept line counting the rest."""
    glyph, word, colour, age = _state(s, now)
    gauge = f"focus:{t.get('name')}/{s.get('key')}:ctx"
    effort = s.get("effort") or "?"
    level = {"low": 1, "medium": 2, "high": 3, "xhigh": 4, "max": 5}.get(effort, 0)
    cost = s.get("cost") or {}
    flags = _flags(s)
    rows = [_fit([(_c("effort ", "dim") + _c("▮" * level, "coral") + _c("▯" * (5 - level), "faint")
                   + _c(f" {effort}", "coral bold") + _c("   role ", "dim")
                   + _c(s.get("role") or "?", ROLE.get(s.get("role"), "dim")), 0),
                  (_c(f" · {t.get('name') or '?'}", "dim"), 1)], width - 4),
            _focus_context(s, gauge, motion),
            _c(_usd(cost.get("session_usd")), "bold") + _c(" session   ", "dim")
            + _c(_usd(cost.get("seat_today_usd")) + ("+" if cost.get("seat_today_partial") else ""), "bold")
            + _c(" seat today", "dim"), _cache(s), _tools(s, width - 4), _turns(s, width - 4)]
    rows += _mail(s, width - 4)
    rows += _wrap(_c("flags ", "dim"), flags or [_c("none", "dim")], width - 4)
    spare = room - len(rows) - 2
    if spare < 0:
        return []
    detail = _more(_detail(s), spare) if expanded else []
    return _box(_c(f"{_model(s)} · {s.get('name') or s.get('key') or '?'}", "coral bold"), rows + detail, width,
                "coral", _tag(_c(f"{glyph} {word}", colour), _pulse(word, motion)) + _c(f" {age}", "dim"))


def _lane(a, t0, now, cells, colour, tag):
    start, last = _num(a.get("started")), _num(a.get("last_write"))
    if start is None or last is None:
        return _c("?", "amber")
    span = max(1, now - t0)
    x0 = max(0, min(cells - 1, int((start - t0) / span * cells)))
    x1 = max(x0 + 1, min(cells, int((last - t0) / span * cells) + 1))
    return _c("·" * x0, "faint") + _tag(_c("━" * (x1 - x0), colour), tag) + _c("·" * (cells - x1), "faint")


def _agent_badges(a, now):
    flags = a.get("flags") or {}
    row = []
    if flags.get("stalled"):
        last = _num(a.get("last_write"))
        row += _c(f" stalled {_dur(now - last) if last is not None else '?'} ", "salmon")
    if flags.get("waiting_on_finished_child"):
        row += _c(" waits on finished child ", "salmon")
    if flags.get("orphan"):
        row += _c(" orphan ", "amber")
    return row


def _agent_tail(s, a, now, all_agents):
    start, last = _num(a.get("started")), _num(a.get("last_write"))
    end = last if a.get("finished") else now
    elapsed = _timer(end - start) if end is not None and start is not None else "?"
    tail = _c(f" {elapsed:>5}", "dim") + _agent_badges(a, now)
    return tail + (_c(f" {s.get('name') or '?'}", "dim") if all_agents else [])


def _agent_row(a, i, t0, now, label_width, lane_width, tail, motion):
    flags = a.get("flags") or {}
    glyph, colour = ("✓", "green") if a.get("finished") else ("■", "salmon") if flags.get("stalled") else ("●", "blue")
    indent = "  " * max(0, int(_num(a.get("depth")) or 1) - 1)
    label = _pad(_c(f"{indent}{i}: {a.get('description') or a.get('type') or '?'}"), label_width)
    flow = "~flow" if motion and glyph == "●" else None
    return _c(glyph + " ", colour) + label + _c(" ") + _lane(a, t0, now, lane_width, colour, flow) + tail


def _agents(vis, now, cursor, all_agents, width, expanded, motion):
    chosen = vis if all_agents else vis[cursor:cursor + 1]
    pairs = sorted([(s, a) for _, _, s in chosen for a in _dicts(s.get("agents"))], key=lambda p: _num(p[1].get("started")) or 0)
    if not pairs:
        return []
    running = sum(not a.get("finished") for _, a in pairs)
    head = (_c("agents", "bold") + _c(" · ", "dim") + _c(f"{running} running", "green bold")
            + _c(f" · {len(pairs)} total", "bold") + (_c(" · all sessions", "dim") if all_agents else []))
    rows = [_pad(head, width - 9) + _c(" ⏎ expand", "faint")]
    t0 = min((_num(a.get("started")) for _, a in pairs if _num(a.get("started")) is not None), default=now)
    tails = [_agent_tail(s, a, now, all_agents) for s, a in pairs]
    widest = max(_len(tail) for tail in tails)
    # One group-wide geometry preserves the time axis. Badges take description space down to 10 cells,
    # then track space down to 8; the end of a row is cut only after both floors are reached.
    label_width = max(10, min(22, width - widest - 19))
    lane_width = max(8, min(16, width - label_width - widest - 3))
    for i, ((_, a), tail) in enumerate(zip(pairs, tails), 1):
        rows.append(_agent_row(a, i, t0, now, label_width, lane_width, tail, motion))
        if expanded:
            last = _num(a.get("last_write"))
            rows.append(_c(f"  {a.get('type') or '?'} · {_count(a.get('tokens'))} tokens · last write "
                           f"{_dur(now - last) if last is not None else '?'} ago", "dim"))
    return rows


def _runner_part(runner, motion):
    if runner.get("state") != "live":
        beat = f" (last beat {_dur(runner.get('beat_age_s'))} ago)" if runner.get("state") == "stale" else ""
        return _c(f"no live runner{beat}", "amber")
    used, budget, swap = _num(runner.get("used")), _num(runner.get("budget")), _num(runner.get("swap"))
    count = _c(f" {_g(math.floor(used + 0.5) if used is not None else None)}/{_g(budget)}", "bold")
    row = (_c("budget ", "dim") + _bar(used, budget, 6, "green", _ease(motion, "builds:budget"))
           + (_tag(count, _ease(motion, "builds:budget:n")) if used is not None else count) + _c("   swap ", "dim"))
    if swap is None:
        return row + _c("?", "amber")
    return (row + _bar(swap, 1, 5, "salmon" if runner.get("swap_hold") is True else "green", _ease(motion, "builds:swap"))
            + _tag(_c(f" {swap * 100:.0f}%", "dim"), _ease(motion, "builds:swap:n")))


def _job_name(job):
    return f"{_cap(job.get('team') or '?', TEAM_CAP)} · {_cap(job.get('session') or '?', SESSION_CAP)}"


def _running_row(job, body):
    # Identity, trouble and the timer are required; kind, then cost, then the worktree are kept while they fit.
    cost = _num(job.get("cost"))
    return _fit([(_c("● ", "green") + _c(_job_name(job)), 0),
                 (_c("  pid gone", "salmon") if job.get("pid_alive") is False else [], 0),
                 (_c(f"  {_timer(job.get('running_s'))}", "dim"), 0), (_c(f"  {job.get('kind') or '?'}", "dim"), 1),
                 (_c(f"  cost {'?' if cost is None else f'{cost:.1f}'}", "dim"), 2),
                 (_c(f"  {_tail(job.get('worktree'), JOB_TAIL_CAP)}", "dim"), 3)], body)


def _queued_row(job, body):
    # The hold sits beside the identity it holds back; the estimated start, then the worktree, are kept while they fit.
    return _fit([(_c(f"#{_g(job.get('position'))} {_job_name(job)}", "dim"), 0),
                 (_c(f"  held {job.get('hold')}", "amber") if job.get("hold") else [], 0),
                 (_c(f"  wait {_dur(job.get('waiting_s'))}", "dim"), 0),
                 (_c(f"  start {_clock(job.get('estimated_start'))}", "dim"), 1),
                 (_c(f"  {_tail(job.get('worktree'), JOB_TAIL_CAP)}", "dim"), 2)], body)


def _queue_jobs(queue):
    classes = _dicts(queue.get("classes"))
    running = [j for c in classes for j in _dicts(c.get("running"))]
    queued = [j for c in classes for j in _dicts(c.get("queued"))]
    return classes, running, queued


def _class_rows(classes):
    rows = []
    for c in classes:
        waits = _mapping(c.get("waits"))
        if (_num(waits.get("n")) or 0) > 0:
            rows.append(_c(f"waits {_g(waits.get('window_h'))}h · {c.get('class') or '?'} · {_g(waits.get('n'))} · "
                           f"med {_dur(waits.get('median_s'))} · max {_dur(waits.get('max_s'))}", "dim"))
    return rows


def _build_rows(builds, body, motion=False):
    """BUILDS body rows laid out against body cells; [] unless running or queued jobs, waits,
    a live runner or warms exist."""
    builds = _mapping(builds)
    queue = _mapping(builds.get("queue"))
    runner = _mapping(queue.get("runner"))
    classes, running, queued = _queue_jobs(queue)
    warms = _dicts(builds.get("warms"))
    active = any((_num(_mapping(c.get("waits")).get("n")) or 0) > 0 for c in classes)
    if not (running or queued or active or runner.get("state") == "live" or warms):
        return []
    sweep = "~sweep" if motion and running else None
    strip = _tag(_c("█" * len(running), "green"), sweep) + _c("█" * len(queued), "faint")
    rows = [_clip(strip, body) if body < _len(strip) else strip,
            _c(f"■ {len(running)} running", "green") + _c(f"   ■ {len(queued)} queued", "dim"),
            _runner_part(runner, motion)]
    chips = [_c(c.get("class") or "?", "teal bold")
             + _c(f" {len(_dicts(c.get('running')))}/{'∞' if c.get('ceiling') == 0 else _g(c.get('ceiling'))}", "dim")
             for c in classes]
    rows.append(_listed(chips, body, "  "))
    rows += [_running_row(j, body) for j in sorted(running, key=lambda j: -(_num(j.get("running_s")) or 0))]
    rows += [_queued_row(j, body) for j in queued]
    rows += _class_rows(classes)
    rows += [_c(f"warm {w.get('state') or '?'} {_dur(w.get('elapsed_s'))} {_tail(w.get('worktree'), PATH_CAP)}", "dim")
             for w in warms]
    return rows


def _builds(builds: dict) -> list[Row]:
    """BUILDS body rows for running and queued jobs, runner, class limits, waits and warms (no width;
    the box lays them out against its body). Ignores malformed queue entries and never reads runner load fields."""
    return _build_rows(builds, math.inf)


def _build_box(builds, width, motion):
    rows = _build_rows(builds, width - 4, motion)
    if not rows:
        return []
    queue = _mapping(builds.get("queue"))
    _, running, queued = _queue_jobs(queue)
    right = _c(f"{len(running) + len(queued)} jobs", "dim")
    if queue.get("state") == "?":
        right += _c(" · queue ?", "amber")
    return _box(_c("BUILDS · queue", "green bold"), rows, width, "green", right)


def _messages(t, width, flash):
    if t.get("state") == "v1":
        return []
    m = t.get("messages")
    title = _c("log · ", "dim") + _c(t.get("name") or "?", "bold")
    if not isinstance(m, dict):
        return _box(title, [_c("messages ?", "amber")], width)
    roles = {s.get("name"): ROLE.get(s.get("role"), "dim") for s in t.get("sessions") or []}
    rows = []
    for x in _dicts(m.get("last"))[:10]:
        sender, recipient, kind = x.get("sender") or "?", x.get("recipient") or "?", x.get("kind") or "?"
        row = (_c(_clock(x.get("ts"), True), "faint") + _c(" ") + _pad(_c(sender, roles.get(sender, "dim")), 11)
               + _c(" → ", "dim") + _pad(_c(recipient, roles.get(recipient, "dim")), 11) + _c(" ")
               + _pad(_c(kind, KIND.get(kind, "dim") + " bold"), 7) + _c(f" {x.get('text') or ''}", "dim"))
        lit = flash and (t.get("name"), x.get("id")) in flash
        # Padded here whether it flashes or not, as the session rows are (_team_box).
        rows.append(_tag(_pad(row, width - 4), f"~flash:{t.get('name')}:{x.get('id')}" if lit else None))
    for label, key in (("from", "top_senders"), ("to", "top_recipients")):
        top = [_c(f"{name} {n}", "dim") for name, n in (m.get(key) or [])[:5]]
        rows.append(_c(f"{label} ", "dim") + (_listed(top, width - 4 - len(label) - 1, "  ") if top else _c("–", "dim")))
    right = (_c(f"↓{_g(m.get('delivered_today'))} ", "dim")
             + _c(f"held {_g(m.get('held'))}", "salmon" if m.get("held") else "dim")
             + _c(f" queued {_g(m.get('queued'))} bcast {_g(m.get('broadcasts_today'))}", "dim"))
    return _box(title, rows, width, right=right)


def _worktree_rows(w, body):
    """Path tail and size, then every build part and its size, largest first, wrapping onto continuation rows."""
    parts = _mapping(w.get("parts"))
    colour = "salmon" if sum(_num(parts.get(p)) or 0 for p in BUILD_PARTS[:4]) > BUILD_RED_GB else "dim"
    present = sorted((p for p in BUILD_PARTS if p in parts), key=lambda p: -(_num(parts[p]) or 0))
    return _wrap(_c(f"  {_tail(w.get('path'), PATH_CAP)} {_gb(w.get('size_gb'))}  ", colour),
                 [_c(f"{p} {_gb(parts[p])}", colour) for p in present], body, "  ")


def _disk_groups(teams, width, motion):
    measured = sorted([t for t in teams if isinstance(t.get("disk"), dict)],
                      key=lambda t: -(_num(t["disk"].get("size_gb")) or 0))
    order = measured + [t for t in teams if not isinstance(t.get("disk"), dict)]
    top = max((_num(t["disk"].get("size_gb")) or 0 for t in measured), default=1) or 1
    groups = []
    for t in order:
        disk = t.get("disk")
        name = _column(_c(t.get("name") or "?", "bold"), NAME_CAP + 1)
        if not isinstance(disk, dict):
            groups.append((_fit([(name, 0), (_c("not measured yet", "dim"), 0)], width - 4), []))
            continue
        row = _fit([(name, 0), (_bar(disk.get("size_gb"), top, 12, "blue", _ease(motion, f"disk:{t.get('name')}")), 0),
                    (_c(f" {_gb(disk.get('size_gb')):>7}"), 0)], width - 4)
        groups.append((row, [_worktree_rows(w, width - 4) for w in _dicts(disk.get("worktrees"))[:5]]))
    return groups


def _disk_rows(groups, largest, room):
    # Keep every team. Try fewer whole worktrees per team before sacrificing any largest rows.
    for k in range(5, 0, -1):
        rows = sum(([name] + sum(worktrees[:k], []) for name, worktrees in groups), [])
        if len(rows) + len(largest) + 2 <= room:
            return rows + largest
        if k == 1 and len(rows) + 2 <= room:
            return rows + largest[:room - len(rows) - 2]
    rows = [name for name, _ in groups]
    return rows if len(rows) + 2 <= room else None


def _disk(teams, snap, now, width, room=math.inf, motion=False):
    largest = [_c(f"largest {_gb(x.get('size_gb'))} {x.get('part') or '?'} {_tail(x.get('path'), PATH_CAP)}", "dim")
               for x in _dicts(_mapping(snap.get("builds")).get("largest"))]
    if not teams and not largest:
        return []
    rows = _disk_rows(_disk_groups(teams, width, motion), largest, room)
    if rows is None:
        return []
    at = _num(snap.get("disk_at")) if any(isinstance(t.get("disk"), dict) for t in teams) else None
    right = _free(snap) + _c(f" · {_dur(now - at) if at is not None else '?'} ago", "dim")
    return _box(_c("DISK", "blue bold"), rows, width, right=right)


def _alerts(alerts, width, limit=None):
    if not alerts:
        return []
    shown = alerts if limit is None else alerts[:limit]
    rows = []
    for a in shown:
        colour = "salmon" if a.get("kind") in RED_KINDS else "amber"
        rows.append(_c("▲ ", colour) + _c(_clock(a.get("since")), "faint") + _c(" ")
                    + _column(_c(a.get("team") or "?", "dim"), NAME_CAP + 1) + _c(a.get("text") or a.get("kind") or "?", colour))
    right = _c("newest first", "dim")
    if len(shown) < len(alerts):
        right += _c(f" · +{len(alerts) - len(shown)} more", "dim")
    return _box(_c("ALERTS", "amber bold"), rows, width, "amber", right)


def _keys(width):
    keys = [_c(key, "bold") + _c(f" {word}", "dim") for key, word in (
        ("↑↓ j k", "move"), ("⏎", "expand"), ("a", "all agents"), ("t", "team"), ("d", "disk now"), ("q", "quit"))]
    return _centre(_listed(keys, width), width)


def _join(left, right, left_width, right_width):
    return [_pad(left[i] if i < len(left) else [], left_width) + _c(" ")
            + _pad(right[i] if i < len(right) else [], right_width) for i in range(max(len(left), len(right)))]


def _left(teams, current_team, current, now, width, two_across, motion, flash):
    order = [t for t in teams if t.get("state") != "HALTED" and (t.get("state") == "up" or t.get("sessions"))]
    order.sort(key=lambda t: t is not current_team)
    box_width = (width - 1) // 2 if two_across else width
    boxes = [_team_box(t, now, current, box_width, motion, flash) for t in order]
    rows = []
    if two_across:
        columns = [[], []]
        for box in boxes:
            columns[0 if len(columns[0]) <= len(columns[1]) else 1] += box
        rows = _join(columns[0], columns[1], box_width, box_width)
    else:
        rows = sum(boxes, [])
    rows += _halted(teams, width)
    return rows


def _window(body, cursor_row, room):
    if room >= len(body):
        return body
    if room <= 0:
        return []
    first = max(0, min(cursor_row - room // 2, len(body) - room))
    return body[first:first + room]


def _stack(panels, room=math.inf):
    """Panels in order within room rows. A (rows, gap, keep) panel with gap set gets a blank row above it when
    something precedes it. rows may be a function of the room left after that gap, letting DISK drop detail
    before team rows. A rendered box (keep None) is placed whole or left out; the next panel is still tried.
    An unboxed list (keep = its leading rows, the header) is cut by _more to the room left, and is left out only
    when that room cannot hold its header and the `+n more` line."""
    out = []
    for rows, gap, keep in panels:
        gap = [[]] if gap and out and rows else []
        left = room - len(out) - len(gap)
        rows = rows(left) if callable(rows) else rows
        rows = rows if keep is None else _more(rows, left, keep)
        if rows and len(rows) <= left:
            out += gap + rows
    return out


def _middle(left, focus, dock, cursor_row, room, widths):
    """The rows between the pinned top and bottom. focus(rows) is the focus box within that many rows.
    Two columns: the left window keeps the cursor row and the dock fills from its top. One column with a
    height: reserve up to TEAM_RESERVE rows for teams, allocate focus and dock, then render focus, teams, dock."""
    left_width, right_width = widths
    if left_width != right_width:
        return _join(_window(left, cursor_row, room), _stack([(focus(room), False, None)] + dock, room), left_width, right_width)
    if room == math.inf:
        return left + _stack([(focus(room), False, None)] + dock)
    reserve = min(room, TEAM_RESERVE)
    box = focus(room - reserve)
    rest = _stack(dock, room - reserve - len(box))
    return box + _window(left, cursor_row, room - len(box) - len(rest)) + rest


def _pinned(header, fleet, alerts, keys, height, width):
    """Shorten alerts, fleet cell groups, then the legend; keep header and keys down to two rows."""
    if height < 2:
        return header[:height], [], []
    alert_room = height - len(header) - len(fleet) - 1
    bottom = _alerts(alerts, width, min(ALERT_ROWS, alert_room - 2)) if alert_room >= 2 else []
    while len(header) + len(fleet) + 1 > height and len(fleet) > 2:
        fleet = fleet[:-4] + fleet[-1:]
    if len(header) + len(fleet) + 1 > height:
        fleet = []
    if len(header) + len(fleet) + 1 > height:
        header = header[:1]
    return header + fleet, bottom, [keys]


def render(snap: dict, width: int, *, cursor=0, expanded=None, all_agents=False, team_filter=None,
           alert_log=None, height=None, motion=False, flash=None) -> list[Row]:
    """Boxed canvas, at most width columns. At a fixed height, pin fleet and alerts around the middle and fill
    it as _middle says. Without a height, one-column screens show the whole team stack followed by focus and
    the remaining dock panels. motion adds the `~` tags; flash, a set of (team, message id), lights those log
    lines and their recipients' rows, and only with motion."""
    snap = snap or {}
    width = max(0, width)
    flash = flash if motion else None
    now = _num(snap.get("at")) or 0
    teams, vis = _teams(snap, team_filter), visible(snap, team_filter)
    cursor = max(0, min(cursor, len(vis) - 1))
    sid, team, session = vis[cursor] if vis else (None, None, None)
    is_expanded = sid is not None and sid in (expanded or ())
    alerts = _dicts(snap.get("alerts") if alert_log is None else alert_log)
    header, fleet, keys = _header(snap, teams, alerts, width, team_filter), _fleet(teams, snap, width, motion), _keys(width)
    # A 53-column dock plus one separator leaves 66 columns for teams at width 120;
    # wider screens give the additional space to the team boxes.
    left_width, right_width = (width - 54, 53) if width >= 120 else (width, width)
    left = _left(teams, team, session, now, left_width, width >= 180, motion, flash)

    def focus(room):
        return _focus(session, team, now, right_width, is_expanded, room, motion) if session is not None else []

    # The agents list cuts below its header; BUILDS and log stay whole or absent. DISK fits the room left,
    # dropping whole worktrees and largest rows before omitting the box if its team rows and borders cannot fit.
    dock = [(_agents(vis, now, cursor, all_agents, right_width, is_expanded, motion), True, 1),
            (_build_box(_mapping(snap.get("builds")), right_width, motion), True, None),
            (_messages(team, right_width, flash) if team is not None else [], False, None),
            (lambda room: _disk(teams, snap, now, right_width, room, motion), False, None)]
    if height is not None:
        top, bottom, key_rows = _pinned(header, fleet, alerts, keys, max(0, height), width)
        room = max(0, height - len(top) - len(bottom) - len(key_rows))
    else:
        top, bottom, key_rows, room = header + fleet, _alerts(alerts, width), [keys], math.inf
    cursor_row = next((i for i, row in enumerate(left) if any("▸" in text for text, _ in row)), 0)
    middle = _middle(left, focus, dock, cursor_row, room, (left_width, right_width))
    return [_clip(row, width) for row in top + middle + bottom + key_rows]


def palette(colours: int) -> dict[str, int]:
    """Xterm pastels when available; basic curses colours and attribute-only greys otherwise."""
    if colours >= 256:
        return dict(PALETTE)
    import curses
    return {"coral": curses.COLOR_RED, "purple": curses.COLOR_MAGENTA, "teal": curses.COLOR_CYAN,
            "blue": curses.COLOR_BLUE, "green": curses.COLOR_GREEN, "sky": curses.COLOR_CYAN,
            "amber": curses.COLOR_YELLOW, "salmon": curses.COLOR_RED, "dim": -1, "edge": -1, "faint": -1,
            "orange": curses.COLOR_YELLOW, "pulse2": curses.COLOR_GREEN, "pulse3": -1}


def _placements(rows: list[Row], height: int, width: int) -> list[tuple[int, int, str, str | None]]:
    """Clip segments to the screen; omit the bottom-right cell to avoid curses' scroll/error on writing it."""
    out = []
    for y, row in enumerate(rows[:max(0, height)]):
        x = 0
        for text, colour in _clip(row, width - (y == height - 1)):
            if text:
                out.append((y, x, text, colour))
            x += len(text)
    return out


@functools.cache
def _colour_attrs(curses):
    """{colour word: curses attr}, set up once per process: draw runs on every refresh and key, and the frame
    loop reuses the same attrs."""
    curses.start_color()
    curses.use_default_colors()
    attrs = {}
    for pair, (word, colour) in enumerate(palette(curses.COLORS).items(), 1):
        if colour < 0:
            attrs[word] = curses.A_DIM
        else:
            curses.init_pair(pair, colour, -1)
            attrs[word] = curses.color_pair(pair)
    attrs["bold"] = curses.A_BOLD
    return attrs


def draw(stdscr, rows: list[Row]) -> None:
    """Draw full-width rows with the terminal's palette, skipping only its bottom-right cell. Motion's `~` words
    are not colours and are skipped, so tagged rows draw as their still frame."""
    import curses
    attrs = _colour_attrs(curses)
    height, width = stdscr.getmaxyx()
    stdscr.erase()
    for y, x, text, colour in _placements(rows, height, width):
        attr = curses.A_NORMAL
        for word in (colour or "").split():
            if not word.startswith("~"):
                attr |= attrs[word]
        stdscr.addstr(y, x, text, attr)
    stdscr.refresh()
