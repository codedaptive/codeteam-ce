"""The runtime: a team's sessions in herdr, and the loop that runs them.

One herdr workspace per team: a `staff` tab (the orchestrator, assistants, and the codeteam2
daemon) and one tab per lane. Each session lives in a pane labelled with its herdr agent name.

The loop (`codeteam2 run`) reads every session's real state from herdr each tick and acts on
facts instead of guesses:
- messages are delivered (herdr `agent prompt`) only when their recipient is idle or done (or herdr
  shows it working while its own turn has ended: between_turns), never into a blocked agent (herdr
  refuses that itself as well). Everything waiting for a session goes in one prompt, so a burst of messages costs one wake, not one each (2026-10-25: sessions
  were woken too often). A message waits up to gather_s for others to join it;
  runtime commands (/compact, the resume line, /exit) always go alone;
- a lane with mail that is not running is started, up to the lane cap; at the cap, a lane that
  has been idle longer than swap_idle_min with nothing waiting is sent /exit to make room, except a
  lane the user put on hold (team/held/<key>), or one whose pane shows a subagent's view or whose input
  box holds unsent text (it keeps its slot; the next idle lane goes instead);
- an agent blocked longer than blocked_alert_min is reported to the orchestrator (and the owner gets a
  herdr notification), once per episode;
- nothing is typed into a session whose input box holds unsent text (someone is typing), or whose
  pane shows a subagent's view instead of its main conversation (what is typed would reach that
  agent); its mail waits, and the owner is told if that lasts draft_alert_min with real mail queued;
- held mail (refused, or three prompts without a turn) waits for a change: it goes back to the queue
  when the session's herdr status changes, it completes a turn, or the loop starts. Three prompts without a
  turn also open the session's no-turn episode: the orchestrator gets one NOTE naming the messages newly held
  and the owner one notice, and nothing is prompted to that session until the episode ends (those changes, herdr's
  state_change_seq moving, or a [codeteam] prompt later in its transcript). When that prompt ends
  the episode, held messages its headers name are delivered; only the rest return to the queue;
- a session started for mail gets that mail in its first prompt;
- ride-along messages (codeteam's own reports, such as patrol's) never start or wake anyone: they
  go with the next prompt that delivers real mail;
- a session idle idle_exit_h with nothing waiting is ended, except the ones the user talks to, a
  session the user put on hold, and one whose pane shows a subagent's view or whose input box holds unsent text;
- v1's patrol checks run every patrol_min; a turn that ends on an API error is reported once.
`plan()` holds the scheduling rules as a pure function, so they are tested without herdr.
"""
from collections.abc import Mapping
import datetime as dt
import fcntl
import os
import re
import time
import traceback

from . import patrol as patrol_mod
from . import screen as screen_mod
from .herdr import Herdr, HerdrError
from .store import FLAG_NO_TURN_NOTED, RUNTIME, Store
from .team import CODETEAM2, Session, Team
from .transport import PromptTransport, Refused

READY = ("idle", "done")
START_GRACE_S = 120          # allow a recorded start time for the session to appear before retry or mail recovery
TURN_GRACE_S = 50            # after a delivery, wait this long for the turn to show before the next.
                             # Claude Code writes a prompt to the transcript only after its UserPromptSubmit
                             # hooks finish, and they may take their whole 30 s timeout (2026-11-06: a team's
                             # prompt-hook under load; 25 s here put back prompts that were running)
STOP_GRACE_S = 90            # after /exit, the lane counts as leaving for this long
GATHER_S = 30                # a message waits this long for others to join its prompt (bounded)
WARM_S = 240                 # a session whose turn ended this recently is prompted at once: its prompt
                             # cache is still warm, so a wake is cheap and waiting only adds delay
BUNDLE_MAX = 10              # messages in one prompt at most
LEAD_TAB = "orc"             # the orchestrator and designers' tab
STAFF_TAB = "staff"          # the other standing sessions and the loop
READY_STABLE_S = 12          # ready and quiet this long, well after its start: a session's first turn has run
PANE_CLOSE_DELAY_S = 5    # after a stopped session exits, before its bare-shell pane is closed
REACT_S = 1.0                # cap the pause after a deferred planned action to re-observe sooner without spinning
REACT_MAX = 10               # a failing acting call also stamps Herdr.last_action: repeated deferral could
                             # otherwise re-tick indefinitely; after this many quick pauses, sleep poll_s once


def ts():
    return time.time()


LOCAL_COMMAND = ("<command-name>", "<local-command-stdout>", "<local-command-stderr>", "<local-command-caveat>")


def _local_command(r):
    c = (r.get("message") or {}).get("content")
    text = c if isinstance(c, str) else ""
    return text.lstrip().startswith(LOCAL_COMMAND)


PASTED_OPEN = re.compile(r"<pasted_content\b[^>]*>\s*")


def _codeteam_prompt(text):
    """True when a user record's text is codeteam's prompt: it starts with "[codeteam]", or Claude Code wrapped it
    as a long typed prompt, `<pasted_content id="189a"> [codeteam] ...` (2.1.307). A task
    notification, and pasted content that is not a [codeteam] prompt, are not."""
    text = text.lstrip()
    m = PASTED_OPEN.match(text)
    return (text[m.end():] if m else text).startswith("[codeteam]")


def transcript_state(path, tail=400_000):
    """Turn state and last [codeteam] prompt epoch (or None), scanned from the transcript tail."""
    return _transcript_scan(path, tail)[:2]


def last_enqueue(path, tail=400_000):
    """The epoch of the transcript's last queue-operation enqueue record, or None. Claude Code writes one the
    moment a prompt typed during a turn joins its queue (the prompt itself is written only when it runs), so
    it shows a delivered prompt was taken in (2026-11-06: a request was queued behind a six-minute
    turn, then typed twice more)."""
    import json
    for line in reversed(_tail_lines(path, tail) or []):
        if '"queue-operation"' not in line or '"enqueue"' not in line:
            continue
        try:
            r = json.loads(line)
            if r.get("type") == "queue-operation" and r.get("operation") == "enqueue":
                return dt.datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")).timestamp()
        except (ValueError, KeyError, AttributeError):
            continue
    return None


def transcript_usage(path, tail=400_000):
    """(epoch of the transcript's last record, context tokens of its last assistant turn, epoch of its last
    [codeteam] prompt); None for what the tail does not show. Context = input + cache read + cache creation tokens
    of the last assistant message: what the next turn re-reads."""
    import json
    lines = _tail_lines(path, tail)
    if lines is None:
        return None, 0, None
    last, ctx = None, None
    for line in reversed(lines):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if last is None and r.get("timestamp"):
            try:
                last = dt.datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")).timestamp()
            except (ValueError, AttributeError):
                pass
        if ctx is None and r.get("type") == "assistant":
            u = (r.get("message") or {}).get("usage") or {}
            if u:
                ctx = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens",
                                                       "cache_creation_input_tokens"))
        if last is not None and ctx is not None:
            break
    return last, ctx or 0, _transcript_scan(path, tail)[1]


REFRESH_COMMANDS = ("/refocus", "/prepare-for-compact",
                    "/compact Keep the Refocus report and the handoff above verbatim as the working state. "
                    "Summarize everything before them in a few lines.",
                    "/recover-from-compact")


def _tail_lines(path, tail):
    """Read decoded lines from the transcript tail, or None when the file cannot be read."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - tail))
            return f.read().decode("utf-8", "ignore").splitlines()
    except OSError:
        return None


def _record_state(r):
    """A relevant system, user or assistant record's turn state; local commands also count as ended.
    A user record with isCompactSummary true returns None: a compaction summary is not a turn. A scan
    can therefore use an earlier relevant record, whether it indicates an ended or an in-progress turn.
    """
    t = r.get("type")
    if t == "user" and r.get("isCompactSummary") is True:
        return None
    if t == "system" and r.get("subtype") in ("turn_duration", "stop_hook_summary"):
        return "ended"
    if t == "user" and _local_command(r):
        return "ended"         # a slash command run by hand (/mcp): it starts no turn
    if t in ("user", "assistant"):
        return "in-turn"
    return None


def _record_prompt(r):
    """Return a [codeteam] user prompt's epoch and text, or None when it is not such a prompt.
    An invalid or missing timestamp gives epoch 0. Text blocks are joined with spaces. _codeteam_prompt
    recognizes bare and pasted prompts so their text can identify held mail."""
    if r.get("type") != "user":
        return None
    c = (r.get("message") or {}).get("content")
    text = c if isinstance(c, str) else " ".join(b.get("text", "") for b in c if isinstance(b, dict)) \
        if isinstance(c, list) else ""
    if not _codeteam_prompt(text):
        return None
    try:
        prompt = dt.datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")).timestamp()
    except (KeyError, ValueError):
        prompt = 0.0
    return prompt, text


def _transcript_scan(path, tail=400_000):
    """Scan the transcript tail for turn state and the last [codeteam] prompt's epoch and text.
    The latest relevant record determines state; missing prompt fields are None."""
    import json
    lines = _tail_lines(path, tail)
    if lines is None:
        return "?", None, None
    state, prompt, prompt_text = None, None, None
    for line in reversed(lines):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if state is None:
            state = _record_state(r)
        if prompt is None:
            found = _record_prompt(r)
            if found is not None:
                prompt, prompt_text = found
        if state is not None and prompt is not None:
            break
    return state or "?", prompt, prompt_text


def prompt_header(m: Mapping[str, object]) -> str:
    """Format the header shared by outgoing bundles and held-message matching."""
    return f"#{m['id']} {m['kind']} from {m['sender']} to {m['recipient']}:"


def prompt_names(text: str, m: Mapping[str, object]) -> bool:
    """Match the exact message header at a line start, optionally after `[codeteam] `, in bare or pasted text.
    Mid-line citations do not match; a body line copying the header does."""
    text = text.lstrip()
    pasted = PASTED_OPEN.match(text)
    if pasted:
        text = text[pasted.end():]
    return re.search(r"^(?:\[codeteam\] )?" + re.escape(prompt_header(m)), text, re.MULTILINE) is not None


def _kind(item):
    return item[2] if len(item) > 2 else ""


def _ride(item):
    return bool(item[3]) if len(item) > 3 else False


def real(items):
    """The items that may start or wake a session: everything but ride-along messages."""
    return [it for it in (items or []) if not _ride(it)]


def bundle(items, now, gather_s):
    """The mids to deliver now from a session's waiting items [(mid, ts_epoch[, kind[, ride]])],
    oldest first, or () to wait. A runtime command goes alone, in order. Messages go together, up to
    BUNDLE_MAX, once the oldest real one has waited gather_s (so a burst arrives as one prompt, and
    no message waits longer than gather_s for company). Ride-along messages go only with a real
    one, never alone."""
    if not items:
        return ()
    if _kind(items[0]) == RUNTIME:
        return (items[0][0],)
    head = []
    for it in items:
        if _kind(it) == RUNTIME:
            break
        head.append(it)
    reals = real(head)
    if not reals and len(head) < len(items):
        # Only ride-alongs before a runtime command: they cannot go alone, so the command goes next and they wait
        # for a real message after it. Without this the command was never first and nothing was ever delivered
        # again (an orchestrator, 2026-11-06: 124 messages stuck for 3 h behind a /compact queued after
        # 19 patrol notes).
        return (items[len(head)][0],)
    if not reals or now - reals[0][1] < gather_s:
        return ()
    # The real messages first (they are the reason for the wake), then ride-alongs, up to the cap.
    ordered = reals + [it for it in head if _ride(it)]
    return tuple(it[0] for it in ordered[:BUNDLE_MAX])


def last_mids(rec):
    """The mids of the prompt a session is being waited on for (older state files: last_mid)."""
    if rec.get("last_mids"):
        return tuple(rec["last_mids"])
    return (rec["last_mid"],) if rec.get("last_mid") else ()


def plan(sessions, status, pending, st, now, cap, swap_idle_min, blocked_alert_min, gather_s=GATHER_S,
         warm_s=WARM_S, held=frozenset(), idle_exit_min=0, keep_awake=frozenset(), between_turns=frozenset()):
    """sessions: [(key, kind)]; status: key -> absent|idle|done|working|blocked|unknown;
    pending: key -> [(mid, ts_epoch[, kind[, ride]])] oldest first; st: key -> dict (state_since,
    starting_at, delivered_at, awaiting_turn, last_mids, alerted, view: the subagent whose view its pane
    shows, draft_since: since when its input box has held unsent text, both set by Runtime.screen_hold);
    held: sessions the user put on hold (never started or prompted; their mail waits); idle_exit_min: a session idle this long with
    nothing waiting is ended (0: never), except those in keep_awake; between_turns: sessions herdr shows
    working whose own turn has ended (a background lead keeps herdr's status at working): they take mail like a
    ready session, and nothing else (no idle exit, no swap). Returns actions:
    ("start", key), ("deliver", key, (mid, ...)), ("redeliver", key, (mid, ...)),
    ("stop", key, "swap" | "idle"), ("confirm_exit", key), ("alert", key, minutes)."""
    acts = []
    kinds = dict(sessions)
    g = lambda k, f, d=None: st.get(k, {}).get(f, d)
    all_pending = {k: v for k, v in pending.items() if k not in held}
    # Only real mail starts, wakes or keeps a session; ride-along mail just waits for the next prompt.
    pending = {k: real(v) for k, v in all_pending.items() if real(v)}
    # A session found with background work running when it was to be ended for idleness (a training run,
    # a long build) is left alone until bg_until (2026-10-28: an idle exit stopped a lane's
    # background work).
    bg = lambda k: (g(k, "bg_until") or 0) > now
    # A lane whose pane shows a subagent's view, or whose input box holds unsent text, refuses /exit
    # (Runtime.stop). The swap and the over-cap pass skip it and take the next idle lane, and idle exit skips
    # it. It keeps its slot while the view or the draft lasts.
    # A lane in `held` (the user's hold, team/held/<key>) is passed over the same way: `pending` above drops
    # its mail, so it would look mail-free, and Runtime.stop does not check the hold. It stays counted in
    # awake/n_awake, so when every idle lane is on hold or refuses /exit, the waiting lane waits.
    viewed = lambda k: bool(g(k, "view"))
    drafted = lambda k: bool(g(k, "draft_since"))
    st = {k: (v if k not in held else {**v, "wake_requested": None}) for k, v in st.items()}
    starting = {k for k in kinds if status.get(k) == "absent" and now - (g(k, "starting_at") or 0) < START_GRACE_S}
    # Sent /exit recently and still there: leaving. Not counted against the cap, never stopped twice;
    # if Claude asks whether to stop its background work, the answer is yes (confirm_exit).
    leaving = {k for k in kinds if status.get(k, "absent") != "absent" and now - (g(k, "stopping_at") or 0) < STOP_GRACE_S}
    for k in leaving:
        if status.get(k) == "blocked" and not g(k, "exit_confirmed"):
            acts.append(("confirm_exit", k))

    # Staff with mail and not running: start (no cap).
    for k, kind in sessions:
        if kind == "staff" and status.get(k) == "absent" and pending.get(k) and k not in starting:
            acts.append(("start", k))

    # Lanes: wake by oldest mail, up to the cap; at the cap, make room once per tick.
    awake = [k for k, kind in sessions if kind == "lane" and k not in leaving
             and (status.get(k, "absent") != "absent" or k in starting)]
    # A lane waits for a start when it has mail, or when someone asked for it (`codeteam2 launch`).
    def first(k):
        return pending[k][0][1] if pending.get(k) else g(k, "wake_requested")
    waiting = sorted((first(k), k) for k, kind in sessions
                     if kind == "lane" and status.get(k) == "absent" and k not in starting
                     and (pending.get(k) or g(k, "wake_requested")))
    n_awake = len(awake)
    stopped = False
    for _, k in waiting:
        if n_awake < cap:
            acts.append(("start", k))
            n_awake += 1
        elif not stopped:
            victims = sorted((g(v, "state_since", now), v) for v in awake
                             if v not in held and status.get(v) in READY and not pending.get(v) and not bg(v)
                             and not viewed(v) and not drafted(v) and now - g(v, "state_since", now) >= swap_idle_min * 60)
            if victims:
                acts.append(("stop", victims[0][1], "swap"))
                stopped = True

    # Over the cap (a lane started with launch --now, or the cap lowered): idle lanes go, oldest idle first.
    running = [k for k in awake if k not in starting]
    excess = len(running) - cap
    if excess > 0 and not stopped:
        idle = sorted((g(v, "state_since", now), v) for v in running
                      if v not in held and status.get(v) in READY and not pending.get(v) and not bg(v)
                      and not viewed(v) and not drafted(v) and now - g(v, "state_since", now) >= swap_idle_min * 60)
        for _, v in idle[:excess]:
            acts.append(("stop", v, "swap"))

    # Idle a long time with nothing waiting: end it (v1's tick did this at 6 h). Its cache is cold by
    # then, so this costs no tokens; it frees the process. Never the sessions the user talks to.
    if idle_exit_min:
        stopping = {a[1] for a in acts if a[0] == "stop"}
        for k in kinds:
            if k in stopping or k in leaving or k in starting or k in keep_awake or k in held or bg(k) \
                    or viewed(k) or drafted(k):
                continue
            if status.get(k) in READY and not pending.get(k) and not g(k, "awaiting_turn") \
                    and now - g(k, "state_since", now) >= idle_exit_min * 60:
                acts.append(("stop", k, "idle"))

    # Deliveries: one prompt per turn carrying everything queued (see bundle; held mail is not in pending
    # until the loop releases it, and a session with an open no-turn episode has none in pending either: see
    # tick), only to a ready
    # session, and not before its first turn (its startup prompt) has run: herdr can show a fresh
    # session idle for a moment before that turn starts, and a prompt typed then is lost (seen in
    # the smoke run, 2026-10-24).
    for k in kinds:
        s = status.get(k)
        if (s in READY or k in between_turns) and pending.get(k) and k not in leaving:
            if g(k, "starting_at") and not g(k, "first_turn_seen") and now - g(k, "starting_at") < START_GRACE_S:
                # Not proven yet. A session ready and quiet for READY_STABLE_S, well after its start, has run
                # its first turn too (a resumed session's short turn can pass uncounted by herdr while it is
                # still being detected: restart test, 2026-10-26); "a moment" idle before the turn is not that.
                if not (now - g(k, "state_since", now) >= READY_STABLE_S and now - g(k, "starting_at") >= 2 * READY_STABLE_S):
                    continue
            if g(k, "awaiting_turn") and (now - (g(k, "delivered_at") or 0) < TURN_GRACE_S or last_mids(st.get(k, {}))):
                continue        # still waiting for the turn, or the last prompt is being put back first
            # Gather only for a session idle long enough that its cache has gone cold (a costly wake,
            # worth sharing); one that just ended its turn is prompted at once (factory smoke run,
            # 2026-10-25: gathering on every hop made the run 55% slower).
            warm = now - g(k, "state_since", now) < warm_s
            mids = bundle(all_pending[k], now, 0 if warm else gather_s)
            if mids:
                acts.append(("deliver", k, mids))

    # A delivered prompt that never started a turn: put it back (up to 3 tries), then hold it and open the
    # session's no-turn episode (its mail waits for a change in the session; one NOTE and one notice per
    # episode).
    for k in kinds:
        mids = last_mids(st.get(k, {}))
        if g(k, "awaiting_turn") and mids and now - (g(k, "delivered_at") or 0) >= TURN_GRACE_S \
                and (status.get(k) in READY or k in between_turns):
            acts.append(("redeliver", k, mids))

    # Blocked too long: say so once.
    for k in kinds:
        if status.get(k) == "blocked" and not g(k, "alerted") and k not in leaving:
            mins = (now - g(k, "state_since", now)) / 60
            if mins >= blocked_alert_min:
                acts.append(("alert", k, round(mins, 1)))
    return acts


class Runtime:
    def __init__(self, team: Team, log=print, herdr=None, store=None, transport=None):
        """herdr, store and transport can be passed in (tests use fakes); by default they are
        herdr's CLI, the team's SQLite store, and prompts typed through herdr."""
        self.team = team
        self.log = log
        self.herdr = herdr or Herdr(team.herdr_session)
        self.store = store or Store(team.dir / "messages.db", team.dir / "messages.log")
        self.transport = transport or PromptTransport(self.herdr)
        self.obs_at = 0.0
        self.waited = 0
        # Sessions this loop has observed at least once. A session's first tick in this process releases its
        # held mail (a loop start is a change), whether or not the state file remembers an earlier status.
        self.seen = set()

    # ------------------------------------------------------------------ layout
    def workspace(self, create=True):
        for w in self.herdr.workspaces():
            if w.get("label") == self.team.product:
                return w["workspace_id"]
        if not create:
            return None
        res = self.herdr.workspace_create(str(self.team.t.root), self.team.product)
        self.herdr.tab_rename(res["tab"]["tab_id"], LEAD_TAB)
        return res["workspace"]["workspace_id"]

    def tab_of(self, s: Session):
        """Where a session's pane goes: the orchestrator and designers together in the `orc` tab (the
        sessions the owner talks to), every other staff session in `staff` with the loop, a lane in its own tab
        (2026-10-27)."""
        if s.kind == "lane":
            return s.key
        a = self.team.t.assistants.get(s.key, {})
        return LEAD_TAB if s.key == "orc" or str(a.get("role", "")).lower() == "designer" else STAFF_TAB

    def tab_id(self, ws, label, cwd):
        tabs = {t.get("label"): t for t in self.herdr.tabs(ws)}
        if label in tabs:
            return tabs[label]["tab_id"], None
        res = self.herdr.tab_create(ws, cwd, label)
        return res["tab"]["tab_id"], res["root_pane"]["pane_id"]

    def panes_by_label(self, ws):
        return {p.get("label"): p for p in self.herdr.panes(ws) if p.get("label")}

    def ensure_pane(self, s: Session, ws=None):
        ws = ws or self.workspace()
        panes = self.panes_by_label(ws)
        if s.agent in panes:
            return panes[s.agent]["pane_id"]
        if s.kind == "lane":
            res = self.herdr.tab_create(ws, str(s.cwd), s.key)
            pane = res["root_pane"]["pane_id"]
        else:
            tab, _ = self.tab_id(ws, self.tab_of(s), str(self.team.t.root))
            in_tab = [p for p in self.herdr.panes(ws) if p.get("tab_id") == tab]
            free = [p for p in in_tab if not p.get("label")]
            if free:
                pane = free[0]["pane_id"]
            else:
                anchor = in_tab[-1]["pane_id"]
                pane = self.herdr.pane_split(anchor, "right" if len(in_tab) % 2 else "down", str(s.cwd))["pane"]["pane_id"]
        self.herdr.pane_rename(pane, s.agent)
        return pane

    def ensure_daemon_pane(self, ws=None):
        """The loop runs in a pane of the staff tab, so it is visible next to the sessions it runs."""
        ws = ws or self.workspace()
        label = f"{self.team.product}-codeteam2"
        panes = self.panes_by_label(ws)
        if label in panes:
            return panes[label]["pane_id"], False
        tab, root = self.tab_id(ws, STAFF_TAB, str(self.team.t.root))
        in_tab = [p for p in self.herdr.panes(ws) if p.get("tab_id") == tab]
        free = [p for p in in_tab if not p.get("label")]
        if free:
            pane = free[0]["pane_id"]
        else:
            pane = self.herdr.pane_split(in_tab[-1]["pane_id"], "down", str(self.team.t.root))["pane"]["pane_id"]
        self.herdr.pane_rename(pane, label)
        return pane, True

    # ------------------------------------------------------------------ state
    def _read_observation(self, ws):
        panes = self.panes_by_label(ws)
        out = {}
        rename = None
        for s in self.team.sessions():
            p = panes.get(s.agent)
            if not p:
                out[s.key] = ("absent", None, None)
                continue
            if "agent_status" in p and "agent" not in p:
                out[s.key] = ("absent", p["pane_id"], None)
                continue
            try:
                a = self.herdr.agent_get(p["pane_id"])
            except HerdrError as e:
                if e.code != "agent_not_found":
                    raise
                out[s.key] = ("absent", p["pane_id"], None)
                continue
            if rename is None and a.get("name") != s.agent:
                rename = (s, p["pane_id"])
            out[s.key] = (a.get("agent_status", "unknown"), p["pane_id"], a.get("state_change_seq"),
                          a.get("completion_seq"), a.get("terminal_id") or p.get("terminal_id"))
        return out, rename

    def observe(self, ws):
        """Read only this team's labelled agents, rereading after at most one rename.

        Map keys to (status, pane, state_change_seq, completion_seq, terminal_id), or
        ("absent", pane_or_none, None). obs_at precedes the final pane and agent reads.
        """
        self.obs_at = time.monotonic()
        out, rename = self._read_observation(ws)
        if rename is not None:
            s, pane = rename
            try:
                self.herdr.agent_rename(pane, s.agent)
            except HerdrError as e:
                self.log(f"rename {s.key}: {e}")
            self.obs_at = time.monotonic()
            out, _ = self._read_observation(ws)
        return out

    def _waits(self):
        # True when this client acted at or after its last observation: the next acting step waits for a fresh one.
        # Both stamps are monotonic so a wall-clock step cannot put an action before its observation.
        la = getattr(self.herdr, "last_action", None)
        return la is not None and la >= self.obs_at

    # ------------------------------------------------------------------ actions
    def ensure_lane_rendered(self, s: Session) -> None:
        """A lane folder made when its first message arrives has no .claude until the roles are rendered, and a
        session started there exits at once (2026-11-11). Render the roles first. A
        render error is logged and never stops the start."""
        lane_dir = getattr(self.team.t, "lane_dir", None)
        render = getattr(self.team, "render_roles", None)
        if s.kind != "lane" or lane_dir is None or render is None:
            return
        try:
            if not os.path.isdir(os.path.join(str(lane_dir(s.key)), ".claude")):
                render()
                self.log(f"{s.display}: its folder had no .claude; roles rendered before the start")
        except Exception as e:      # a render must never stop a start
            self.log(f"render roles for {s.display}: {type(e).__name__}: {e}")

    def start(self, s: Session, st, resume=False) -> bool:
        self.ensure_lane_rendered(s)
        # Refresh trust at each start: running sessions can rewrite ~/.claude.json and drop another
        # process's entry, leaving a new session at the trust dialog.
        approve = getattr(self.team, "approve_dirs", None)
        if approve:
            try:
                approve()
            except (OSError, ValueError) as e:
                self.log(f"trust: {e}")
        with self.team.state_lock():
            fresh = self.team._read_state()
            prev = fresh.get(s.key, {}).get("starting_at") or 0
            if ts() - prev < START_GRACE_S:
                self.log(f"{s.display}: started {int(ts()-prev)}s ago; not started again")
                return False
            # Pane setup can take several herdr calls; an interruption there must not leave a start record.
            ws = self.workspace()
            pane = self.ensure_pane(s, ws)
            # Record candidates before claiming them so a later tick can recover mail marked delivered
            # if the start is killed. Only claimed non-runtime mail goes in the first prompt, saving a turn.
            # A staff start killed after this record but before pane_run stays down through the grace period;
            # after that, mail or an up can bring it back.
            mail = []
            if getattr(self.team, "mail_in_first_prompt", True):
                mail = [m for m in self.store.pending(s.key) if m["kind"] != RUNTIME][:BUNDLE_MAX]
            starting_at = ts()
            fresh.setdefault(s.key, {}).update({"starting_at": starting_at, "startup_mids": [m["id"] for m in mail]})
            self.team._write_state(fresh)
            mail = [m for m in mail if self.store.mark(m["id"], "delivered", "in the first prompt", only_from="queued")]
            script, sid = self.team.write_launch_script(
                s, resume_sid=st.get(s.key, {}).get("sid") if resume else None,
                mail=self.message_text(s, mail) if mail else None)
            rec = {"sid": sid, "starting_at": starting_at, "awaiting_turn": False, "alerted": False,
                   "wake_requested": None, "first_turn_seen": False, "last_mid": None, "last_mids": [],
                   "startup_mids": [m["id"] for m in mail],
                   # Completed turns are counted per terminal; a larger count proves the first turn ran.
                   "start_completion": st.get(s.key, {}).get("completion_seq") or 0,
                   "start_term": st.get(s.key, {}).get("completion_term")}
            fresh[s.key].update(rec)
            self.team._write_state(fresh)
            pane = self.panes_by_label(ws).get(s.agent, {}).get("pane_id")
            if not pane:
                raise HerdrError("pane", f"no pane labelled {s.agent} after setup")
            self.herdr.pane_run(pane, f"bash {script}")
            st.setdefault(s.key, {}).update(rec)
            self.log(f"start {s.display} in {pane}{' (resume)' if resume else ''}"
                     + (f" with {', '.join('#%d' % m['id'] for m in mail)} in its first prompt" if mail else ""))
            return True

    def screen(self, s: Session):
        """The session's visible screen with its colours, or None if herdr can't read it."""
        try:
            return self.herdr.agent_screen(s.agent)
        except (HerdrError, AttributeError):
            return None

    def screen_hold(self, s: Session, st, esc_ok=False):
        """Why nothing may be typed into the session now, from one read of its screen, or None:
        "agent view" while its pane shows a subagent's view (a prompt would reach that agent, not the session:
        2026-10-29), "typing" while someone has unsent text in its input box (2026-10-25: v1 never typed where the user types; v2 holds instead). Each is said once in the log per
        episode. The owner gets one herdr notification per episode, sent on the first call made once the hold has
        lasted draft_alert_min while real mail (not ride-along) is queued for the session; a hold with no such
        mail queued notifies nobody, and mail queued later in the same episode is notified then. The minutes
        in the notice are the hold's duration. typing_guard = false turns off the draft check only; the view
        check always runs. A screen that cannot be read (None) holds nothing: the mail is typed."""
        mail = []
        def mail_waits():
            # Looked up only when a notice is due, and once per call. Queued rows only: the notice says the
            # mail follows once the view is left or the text is sent or cleared, and only queued mail does.
            # Held mail goes back to the queue on a status change, a completed turn or a loop start, not when
            # the hold ends. Ride-along rows are not real mail (plan skips them too): they start and wake
            # nothing, so they would not "follow".
            if not mail:
                mail.append(any(not m["ride"] for m in self.store.pending(s.key)))
            return mail[0]
        text = self.screen(s)
        if text and screen_mod.task_list_focused(text) and esc_ok:
            # The keyboard is in the background-tasks list (someone pressed ↓ past the box). A prompt typed now is
            # lost: Esc gives the keyboard back to the input box (the session's own turn has ended, so Esc
            # interrupts nothing), and the mail goes on the next tick.
            rec = st.setdefault(s.key, {})
            try:
                self.herdr.agent_send_keys(s.agent, "esc")
                if not rec.get("tasklist_noted"):
                    self.log(f"{s.display}: keyboard was in its background-tasks list; Esc back to the input box")
                rec["tasklist_noted"] = True
            except HerdrError as e:
                self.log(f"{s.display}: Esc out of its tasks list: {e}")
            return "task list"
        if not (text and screen_mod.task_list_focused(text)):
            st.setdefault(s.key, {})["tasklist_noted"] = False
        view = screen_mod.agent_view(text) if text else None
        d = screen_mod.draft(text) if text and getattr(self.team, "typing_guard", True) else None
        rec = st.setdefault(s.key, {})
        alert_min = getattr(self.team, "draft_alert_min", 10)
        if not view:
            rec.update({"view_since": None, "view": None, "view_alerted": False})
        else:
            if not rec.get("view_since"):
                rec["view_since"] = ts()
                self.log(f"{s.display}: its pane shows {view}'s view, not its main conversation; holding its mail")
            rec["view"] = view
            mins = (ts() - rec["view_since"]) / 60
            if mins >= alert_min and not rec.get("view_alerted") and mail_waits():
                rec["view_alerted"] = True
                self.herdr.notify(f"codeteam {self.team.product}: {s.display} shows {view}'s view",
                                  f"Mail for {s.display} is waiting while its pane shows {view}'s view, not its main "
                                  f"conversation ({int(mins)} min). Go back to its main conversation and the mail "
                                  f"follows.")
        if not d:
            rec.update({"draft_since": None, "draft_alerted": False})
        else:
            if not rec.get("draft_since"):
                rec["draft_since"] = ts()
                self.log(f"{s.display}: unsent text in its input box; holding its mail ({d[:60]!r})")
            mins = (ts() - rec["draft_since"]) / 60
            if mins >= alert_min and not rec.get("draft_alerted") and mail_waits():
                rec["draft_alerted"] = True
                self.herdr.notify(f"codeteam {self.team.product}: {s.display} has unsent text",
                                  f"Mail for {s.display} is waiting while its input box holds text you have not sent "
                                  f"({int(mins)} min). Send or clear it and the mail follows.")
        return "agent view" if view else "typing" if d else None

    def stop(self, s: Session, st, reason="asked"):
        """/exit, unless someone is typing into it or its pane shows a subagent's view (where /exit would reach
        that agent, not the session): then False. plan passes over a lane recorded in a subagent's view or with a
        draft until the tick clears the record (its screen read, or the session no longer running).
        reason: "asked" (sleep, down) stops background work too; "idle" and "swap" leave a session that has
        background work running (see confirm_exit)."""
        if self.screen_hold(s, st, esc_ok=True):
            return False
        try:
            self.herdr.agent_prompt(s.agent, "/exit")
            st.setdefault(s.key, {}).update({"stopping_at": ts(), "exit_confirmed": False, "stop_reason": reason})
            self.log(f"stop {s.display} (/exit, {reason})")
            return True
        except HerdrError as e:
            self.log(f"stop {s.display}: {e}")
            return False

    def confirm_exit(self, s: Session, st):
        """Claude asks before /exit when background work runs (a lane's mail watcher): the first
        choice is "Exit and stop tasks". Answer it only when that is the dialog on screen."""
        st.setdefault(s.key, {})["exit_confirmed"] = True
        try:
            screen = self.herdr.agent_read(s.agent, lines=20)
        except HerdrError as e:
            self.log(f"confirm exit {s.display}: {e}")
            return
        if "Background work is running" in screen and "Exit and stop tasks" in screen:
            rec = st.setdefault(s.key, {})
            if rec.get("stop_reason") in ("idle", "swap"):
                # Ended only for idleness: its background work (a run, a build) matters more. Cancel the
                # exit and leave it for an hour.
                self.herdr.agent_send_keys(s.agent, "esc")
                rec.update({"stopping_at": None, "bg_until": ts() + 3600})
                self.log(f"exit {s.display} cancelled: background work is running; left alone for an hour")
                return
            self.herdr.agent_send_keys(s.agent, "enter")
            self.log(f"confirm exit {s.display}: background work stopped")
        else:
            self.log(f"confirm exit {s.display}: unexpected dialog left for a person")

    def transcript(self, rec):
        """The session's Claude Code transcript (~/.claude/projects/<dir>/<sid>.jsonl; a resume appends to it)."""
        sid = rec.get("sid")
        if not sid:
            return None
        p = rec.get("transcript")
        if p and os.path.basename(p) == f"{sid}.jsonl" and os.path.exists(p):
            return p
        import glob
        hits = sorted(glob.glob(os.path.expanduser(f"~/.claude/projects/*/{sid}.jsonl")), key=os.path.getmtime)
        if hits:
            rec["transcript"] = hits[-1]
            return hits[-1]
        return None

    def between_turns(self, k, rec, now):
        """True when the transcript's last relevant record says the session's own turn has ended.
        Records with no _record_state verdict are skipped, including compaction summaries. A background agent
        can keep herdr at working after the session's turn has ended, so transcript state can permit delivery.
        When awaiting_turn, the last [codeteam] prompt or last enqueue with a nonzero epoch at least
        delivered_at minus two seconds clears the flag; this tolerance allows for delivery timing differences.
        The return value depends only on transcript state. plan applies the awaiting_turn hold to deliveries.
        """
        p = self.transcript(rec)
        if not p:
            return False
        state, last_prompt = transcript_state(p)
        if rec.get("awaiting_turn") and last_prompt and last_prompt >= (rec.get("delivered_at") or 0) - 2:
            rec["awaiting_turn"] = False         # a recent [codeteam] prompt appears in the transcript
        if rec.get("awaiting_turn"):
            enq = last_enqueue(p)
            if enq and enq >= (rec.get("delivered_at") or 0) - 2:
                rec["awaiting_turn"] = False     # a recent enqueue indicates a prompt joined Claude Code's queue
        return state == "ended"

    def refresh_idle(self, status, pending, st, now, held, sessions):
        """An idle session with a big context is refreshed while its 1-hour cache is still warm (2026-11-09):
        /refocus, /prepare-for-compact, /compact, /recover-from-compact, queued as runtime commands that the loop
        types one per turn. Only when: idle (herdr idle or done) and its transcript's last record is between
        refresh_idle_min (50) and refresh_cold_min (58) old, so the cache is warm for all four; its last turn's
        context is at least refresh_min_tokens (150,000); no mail queued or held for it; no subagent view, unsent
        text or awaited turn; not held; not in refresh_skip; and, after an earlier refresh, a [codeteam] prompt has
        run since (one refresh per stretch of work). Returns the sessions it queued."""
        cfg = self.team.cfg
        idle_s = float(cfg.get("refresh_idle_min", 50)) * 60
        if idle_s <= 0:
            return []
        cold_s = float(cfg.get("refresh_cold_min", 58)) * 60
        min_tok = int(cfg.get("refresh_min_tokens", 150_000))
        skip = set(cfg.get("refresh_skip", []))
        cmds = cfg.get("refresh_commands") or REFRESH_COMMANDS
        queued = []
        for k, s in sessions.items():
            rec = st.get(k, {})
            if status.get(k) not in READY or k in held or k in skip or s.display in skip:
                continue
            if pending.get(k) or rec.get("view") or rec.get("draft_since") or rec.get("awaiting_turn") \
                    or rec.get("no_turn") or rec.get("stopping_at"):
                continue
            if self.store.pending(k, held=True):
                continue
            p = self.transcript(rec)
            if not p:
                continue
            last, ctx, prompt = transcript_usage(p)
            if last is None or not (idle_s <= now - last < cold_s) or ctx < min_tok:
                continue
            if rec.get("refreshed_at") and not (prompt and prompt > rec["refreshed_at"]):
                continue
            for c in cmds:
                self.store.add("runtime", "codeteam", RUNTIME, s.display, s.key, c)
            st.setdefault(k, {}).update({"refreshed_at": now, "refresh_ctx": ctx})
            self.log(f"{s.display}: idle {(now - last) / 60:.0f} min at {ctx // 1000}k tokens; refresh queued "
                     f"({', '.join(c.split()[0] for c in cmds)})")
            queued.append(k)
        return queued

    def message_text(self, s: Session, msgs):
        """The prompt for one runtime command (typed as is) or for one or more messages."""
        if isinstance(msgs, dict) or hasattr(msgs, "keys"):
            msgs = [msgs]
        if msgs[0]["kind"] == RUNTIME:
            return msgs[0]["body"]
        senders = {m["sender"] for m in msgs}
        to = senders.pop() if len(senders) == 1 else "<to>"
        say = f"{CODETEAM2} say {self.team.t.manifest} general {s.display} ANSWER {to}"
        parts = [f"{prompt_header(m)}\n{m['body']}" for m in msgs]
        head = "[codeteam] " + ("" if len(msgs) == 1 else f"{len(msgs)} messages for you, oldest first:\n\n")
        return head + "\n\n".join(parts) + f"\n(Reply or report with: {say} \"<text>\")"

    def deliver(self, s: Session, mids, st):
        mids = (mids,) if isinstance(mids, int) else tuple(mids)
        msgs = [m for m in (self.store.get(x) for x in mids) if m]
        if not msgs:
            return
        if self.screen_hold(s, st, esc_ok=True):
            return                  # someone types into it, or it shows a subagent's view: stays queued, tried next tick
        try:
            self.transport.deliver(s.agent, self.message_text(s, msgs))
        except Refused as e:
            for m in msgs:
                self.store.mark(m["id"], "held", e.code)
            self.log(f"deliver {', '.join('#%d' % m['id'] for m in msgs)} to {s.display}: held ({e.code}) until "
                     f"something changes for it")
            return
        for m in msgs:
            self.store.mark(m["id"], "delivered")
        rec = st.setdefault(s.key, {})
        rec.update({"delivered_at": ts(), "awaiting_turn": True, "last_mids": [m["id"] for m in msgs],
                    "last_mid": None, "delivered_seq": rec.get("seq")})
        self.log(f"deliver {', '.join('#%d %s' % (m['id'], m['kind']) for m in msgs)} to {s.display}")

    def redeliver(self, s: Session, mids, st):
        """The prompt started no turn: put its messages back, or after 3 prompts hold them. Holding starts the
        session's no-turn episode (rec["no_turn"]): its mail waits, none is delivered to it, until
        something changes for it (see tick). The orchestrator gets ONE NOTE naming the messages newly held
        (those without the row's FLAG_NO_TURN_NOTED bit, so a message is named once across releases and loop
        restarts) and the owner ONE herdr notice; an episode of messages all named before is silent. A message no
        longer delivered (a person dropped it while it awaited its turn) is left as it is: the state file this
        reads can be older than the drop, and each write applies only while the row is still delivered, so a
        drop landing between the read and the write holds too."""
        mids = (mids,) if isinstance(mids, int) else tuple(mids)
        rec = st.setdefault(s.key, {})
        rec.update({"awaiting_turn": False, "last_mid": None, "last_mids": []})
        held, named = [], []
        for mid in mids:
            m = self.store.get(mid)
            if not m or m["state"] != "delivered":
                continue
            if m["attempts"] >= 3:
                if not self.store.mark(mid, "held", "no turn after 3 prompts", flags=FLAG_NO_TURN_NOTED,
                                       only_from="delivered"):
                    continue
                held.append(mid)
                if not m["flags"] & FLAG_NO_TURN_NOTED:
                    named.append(f"#{mid} ({m['kind']} from {m['sender']})")
                continue
            if self.store.mark(mid, "queued", "prompt started no turn; put back", only_from="delivered"):
                self.log(f"#{mid} to {s.display}: prompt started no turn; put back")
        if not held:
            return
        # The episode is recorded before anything is posted: a post that raises leaves the mail waiting, not
        # prompted again next tick.
        p = self.transcript(rec)
        rec["no_turn"] = {"seq": rec.get("seq"), "prompt": transcript_state(p)[1] if p else None, "since": ts()}
        self.log(f"{s.display}: no turn after 3 prompts; held {', '.join('#%d' % m for m in held)} until something "
                 f"changes for it (no-turn episode)")
        if not named:
            return
        what = (f"three prompts started no turn; its mail waits until something changes for it. "
                f"Look at its pane: herdr agent read {s.agent}.")
        if s.key != "orc":
            self.store.add("general", "codeteam", "NOTE", self.team.t.orc_name(), "orc",
                           f"codeteam could not get {', '.join(named)} to {s.display}: {what}")
        self.herdr.notify(f"codeteam {self.team.product}: {s.display} takes no turn",
                          f"{s.display}: {what} Held: {', '.join(named)}.")

    def alert(self, s: Session, mins, st):
        st.setdefault(s.key, {})["alerted"] = True
        text = f"{s.display} has been blocked for {mins} min (a question or permission dialog in its pane)."
        self.herdr.notify(f"codeteam {self.team.product}: {s.display} blocked", text)
        if s.key != "orc":
            self.store.add("general", "codeteam", "NOTE", self.team.t.orc_name(), "orc",
                           text + f" Look at it with: herdr agent read {s.agent} (HERDR_SESSION={self.team.herdr_session}).")
        self.log(f"alert: {text}")

    def ingest_v1_inboxes(self):
        """codeteam v1's process commands (push-up, approve, integrate, ...) still post their notes the
        v1 way, into the sessions' inbox files. Bring those into the store so they are delivered like
        any message (found in the smoke run: PUSHED notes were sitting unseen). A note to `all` goes to
        the orchestrator as usual, and to every other session only while it is awake."""
        import json as _json
        for s in self.team.sessions():
            box = self.team.t.inbox(s.key)
            if not box.is_dir():
                continue
            for f in sorted(box.glob("*.json")):
                try:
                    msg = _json.loads(f.read_text())
                except (OSError, ValueError):
                    continue
                mid = self.store.add(msg.get("chan", "general"), msg.get("from", "codeteam"), msg.get("type", "NOTE"),
                                     msg.get("to", ""), s.key, msg.get("text", ""))
                # v1: General always reaches the orchestrator; `all` reaches the other staff held, unwoken.
                # So a broadcast is prompted to the orchestrator (it acts on READY) and only recorded for
                # everyone else (found in the factory smoke run: Kong's READY never reached Orc).
                if str(msg.get("to", "")).strip() == "all" and s.key != "orc" \
                        and msg.get("from") not in (self.team.t.orc_name(), "orc"):
                    # Only the orchestrator messages everyone (2026-10-30). A v1 command run by a lane (push-up's
                    # "PUSHED all") reaches the orchestrator alone; it routes the news to whoever needs it.
                    self.store.mark(mid, "delivered", "to all from a lane: the orchestrator's copy is the one")
                elif str(msg.get("to", "")).strip() == "all" and s.key != "orc":
                    # Prompted to an awake session, never a reason to start one (v1 holds it unwoken; an
                    # awake v1 session sees it through its watcher). Factory smoke run: Nagatha waited
                    # for a READY that had been only recorded, and the promote deadlocked.
                    self.store.mark(mid, "queued", "broadcast")
                read = box / "read"
                read.mkdir(exist_ok=True)
                f.replace(read / f.name)
                self.log(f"v1 inbox -> #{mid} {msg.get('type')} from {msg.get('from')} for {s.display}")

    # ------------------------------------------------------------------ the loop
    def _close_exited_pane(self, key: str, rec: dict, status: str, pane: str | None, now: float) -> None:
        # Recheck under the start lock so a stale tick cannot close a newer start's pane.
        with self.team.state_lock():
            if self.team._read_state().get(key, {}).get("starting_at") != rec.get("starting_at"):
                return
            rec["close_pane_at"] = None
            if status != "absent" or not pane or (rec.get("starting_at") or 0) >= now - START_GRACE_S:
                return
            try:
                self.herdr.pane_close(pane)
                self.log(f"{key}: closed its pane {pane} after it exited")
            except HerdrError as e:
                self.log(f"{key}: close pane {pane}: {e}")

    def _put_back_startup_mail(self, key: str, rec: dict) -> None:
        # Recheck under the start lock so a stale tick cannot reclaim mail from a newer start.
        with self.team.state_lock():
            if self.team._read_state().get(key, {}).get("starting_at") != rec.get("starting_at"):
                return
            for mid in rec["startup_mids"]:
                self.store.mark(mid, "queued", "its first prompt never ran; put back", only_from="delivered")
            self.log(f"{key}: did not come up; {len(rec['startup_mids'])} message(s) from its first prompt put back")
            rec["startup_mids"] = []

    def tick(self):
        self.waited = 0
        ws = self.workspace()
        obs = self.observe(ws)
        st = self.team.load_state()
        now = ts()
        status = {k: v[0] for k, v in obs.items()}
        for k, s in status.items():
            rec = st.setdefault(k, {})
            seq = obs[k][2]
            # A turn shorter than one poll is missed by state alone: herdr's state_change_seq moving
            # since the delivery proves the turn happened (found on a test copy, 2026-10-24).
            if rec.get("awaiting_turn") and seq is not None and rec.get("delivered_seq") is not None \
                    and seq > rec["delivered_seq"] + 0:
                rec["awaiting_turn"] = False
                rec["first_turn_seen"] = True
            rec["seq"] = seq
            done_n = obs[k][3] if len(obs[k]) > 3 else None
            term = obs[k][4] if len(obs[k]) > 4 else None
            done_before = rec.get("completion_seq") if rec.get("completion_term") == term else None
            if done_n is not None:
                # herdr counts completed turns per terminal: a session's first turn has run once its
                # terminal has completed more turns than when it was started there (a new terminal: 0).
                base = rec.get("start_completion") if rec.get("start_term") == term else 0
                if rec.get("starting_at") and not rec.get("first_turn_seen") and done_n > (base or 0):
                    rec["first_turn_seen"] = True
                    rec["startup_mids"] = []
                rec.update({"completion_seq": done_n, "completion_term": term})
            was = rec.get("status")
            # Held mail waits for something to change for its session, and a recipient's no-turn episode
            # (rec["no_turn"], opened by redeliver: ) ends on the same changes: the loop starting
            # (this process's first sighting of it: held mail gets one more chance, so none is stranded by a
            # restart), its herdr status, a turn completed on the same terminal, and, for an open episode, its
            # state_change_seq moving from the recorded one (compared only when both are known) or a [codeteam]
            # prompt in its transcript later than the recorded one (read only for an open episode). If that
            # prompt ends the episode, held mail its headers name is delivered; the rest goes back in the queue
            #. Every other ending releases all held mail, and delivery resumes.
            # A session counts as seen only once settlement and release have returned: a release that raises
            # (sqlite "database is locked"; run() logs the tick error and carries on) is retried on the next tick,
            # so held mail for a lane whose status never changes is not stranded, and the episode is cleared
            # only after the release.
            turned = done_n is not None and done_before is not None and done_n > done_before
            first = k not in self.seen
            episode = rec.get("no_turn")
            why = "loop started" if first else \
                f"status {was} -> {s}" if was is not None and was != s else "completed a turn" if turned else None
            if why is None and episode:
                if seq is not None and episode.get("seq") is not None and seq != episode["seq"]:
                    why = f"state_change_seq {episode['seq']} -> {seq}"
                else:
                    p = self.transcript(rec)
                    _, prompt, prompt_text = _transcript_scan(p) if p else ("?", None, None)
                    if prompt is not None and (episode.get("prompt") is None or prompt > episode["prompt"]):
                        why = "a [codeteam] prompt ran in its transcript"
            if why:
                if why == "a [codeteam] prompt ran in its transcript":
                    named = [m["id"] for m in self.store.pending(k, held=True)
                             if m["state"] == "held" and prompt_names(prompt_text, m)]
                    if named:
                        settled = self.store.settle_held(k, named, "delivered: its prompt ran in the transcript")
                        self.log(f"{k}: {', '.join('#%d' % m for m in settled)} delivered by the prompt that ran "
                                 "in its transcript")
                back = self.store.release(k, f"released: {why}")
                if back:
                    self.log(f"{k}: {why}; held {', '.join('#%d' % m for m in back)} back in the queue")
                if episode:
                    rec.pop("no_turn", None)
                    self.log(f"{k}: no-turn episode over: {why}")
            self.seen.add(k)
            if was != s:
                rec.update({"status": s, "state_since": now})
                if s in ("working", "blocked"):
                    rec["awaiting_turn"] = False
                    rec["first_turn_seen"] = True
                    rec["startup_mids"] = []
                    rec["api_error"] = None
                if s != "blocked":
                    rec["alerted"] = False
                if s == "absent":
                    # It exited because codeteam stopped it: its pane, now a bare shell, goes a few seconds
                    # later (2026-10-29: they are clutter, and Claude's drawing leaves no scrollback).
                    # A session that exits on its own keeps its pane, so whatever it printed can be read.
                    if rec.get("stopping_at"):
                        rec["close_pane_at"] = now + PANE_CLOSE_DELAY_S
                    rec["stopping_at"] = None
            if s == "absent":
                # A session not running holds nothing: its view and draft records clear on every tick it is
                # absent, not only on the change, so a state file saved already absent (an earlier loop) is
                # cleared too. show_in_herdr runs later in this tick, so the sidebar's hold token goes too
                #.
                rec.update({"view": None, "view_since": None, "view_alerted": False,
                            "draft_since": None, "draft_alerted": False})
            if rec.get("close_pane_at") and now >= rec["close_pane_at"] and not self._waits():
                self._close_exited_pane(k, rec, s, obs[k][1], now)
                if was == "working" and s in READY:
                    self.check_api_error(k, rec)
            # Recover delivered first-prompt mail only when no newer start owns it; dropped mail stays dropped.
            if rec.get("startup_mids") and s == "absent" and now - (rec.get("starting_at") or 0) >= START_GRACE_S:
                self._put_back_startup_mail(k, rec)
        self.ingest_v1_inboxes()
        pending = {}
        waiting_n = {}              # every message waiting per session, held too: for herdr's sidebar
        for m in self.store.pending(held=True):
            waiting_n[m["target"]] = waiting_n.get(m["target"], 0) + 1
            if m["state"] != "queued":
                continue            # held: it waits for a change in its session (released above), not for a tick
            if st.get(m["target"], {}).get("no_turn"):
                continue            # its recipient's no-turn episode is open: nothing is prompted to it until it
                                    # ends above (still counted in waiting_n)
            if m["note"] == "broadcast" and status.get(m["target"]) == "absent":
                continue            # a broadcast waits for its session to be awake; it does not wake it
            t = dt.datetime.fromisoformat(m["ts"]).timestamp()
            pending.setdefault(m["target"], []).append((m["id"], t, m["kind"], m["ride"]))
        sessions = {s.key: s for s in self.team.sessions()}
        held = {k for k in sessions if getattr(self.team, "held", lambda _k: False)(k)}
        # plan skips a session recorded in a subagent's view or with a draft when it picks one to stop, and
        # without queued mail it gets no delivery, so nothing else reads its screen: read it here, before plan,
        # so the record follows the screen and clears when someone goes back to its main conversation or sends
        # or clears the text. When plan delivers to it, deliver reads the screen again in the
        # same tick.
        for k, s in sessions.items():
            rec = st.get(k, {})
            if status.get(k) != "absent" and (rec.get("view") or rec.get("draft_since")):
                try:
                    self.screen_hold(s, st)
                except HerdrError as e:
                    self.log(f"screen {s.display}: {e}")
        between = set()
        if getattr(self.team, "cfg", {}).get("deliver_between_turns", True):
            for k in sessions:
                rec = st.get(k, {})
                if status.get(k) == "working" and k not in held and (pending.get(k) or rec.get("awaiting_turn")):
                    if self.between_turns(k, rec, now):
                        between.add(k)
        acts = plan([(k, s.kind) for k, s in sessions.items()], status, pending, st, now,
                    self.team.cap, self.team.swap_idle_min, self.team.blocked_alert_min,
                    gather_s=getattr(self.team, "gather_s", GATHER_S), warm_s=getattr(self.team, "warm_s", WARM_S),
                    held=held, idle_exit_min=getattr(self.team, "idle_exit_min", 0),
                    keep_awake=getattr(self.team, "keep_awake", lambda: set())(), between_turns=between)
        if (self.team.dir / "down").exists() or getattr(self.team, "halted", lambda: False)():
            # `codeteam2 down` is ending the team (the loop prompted a lane in the same second down sent it
            # /exit: plugin smoke run, 2026-10-25), or the user halted it (team/HALTED): start and type
            # nothing. Mail is still taken in and patrol still records; nothing reaches a session.
            acts = [a for a in acts if a[0] in ("confirm_exit", "alert")]
        waited = 0
        for a in acts:
            if a[0] != "alert" and self._waits():
                waited += 1
                continue
            s = sessions[a[1]]
            try:
                if a[0] == "start":
                    self.start(s, st, resume=bool(st.get(s.key, {}).get("sid")) and bool(self.team.cfg.get("resume", False)))
                elif a[0] == "deliver":
                    self.deliver(s, a[2], st)
                elif a[0] == "stop":
                    self.stop(s, st, a[2] if len(a) > 2 else "asked")
                elif a[0] == "alert":
                    self.alert(s, a[2], st)
                elif a[0] == "confirm_exit":
                    self.confirm_exit(s, st)
                elif a[0] == "redeliver":
                    self.redeliver(s, a[2], st)
            except HerdrError as e:
                self.log(f"{a[0]} {s.display}: {e}")
        self.waited = waited
        if waited:
            self.log(f"{waited} action(s) wait for a fresh observation: this loop acted after its last observation")
        if not ((self.team.dir / "down").exists() or getattr(self.team, "halted", lambda: False)()):
            try:
                self.refresh_idle(status, pending, st, now, held, sessions)
            except Exception as e:          # a refresh is an economy: it never stops the loop
                self.log(f"refresh_idle: {type(e).__name__}: {e}")
        self.patrol(status, st, now)
        self.backup(st, now)
        self.show_in_herdr(obs, waiting_n, st)
        self.team.save_state(st)
        return acts, status

    def check_api_error(self, key, rec):
        """A turn that ended on an API error (with Claude Code's own retries spent): tell the owner and leave a
        note for the orchestrator's next prompt, once per episode. The session is otherwise idle and
        takes mail as usual."""
        s = self.team.session(key) if hasattr(self.team, "session") else None
        if not s:
            return
        text = self.screen(s)
        err = screen_mod.api_error(text) if text else None
        if not err or rec.get("api_error") == err:
            return
        rec["api_error"] = err
        msg = f"{s.display}'s last turn ended on an API error: {err}"
        self.log(msg)
        self.herdr.notify(f"codeteam {self.team.product}: {s.display} hit an API error", err)
        if key != "orc":
            self.store.add("general", "codeteam", "NOTE", self.team.t.orc_name(), "orc",
                           msg + ". It takes mail as usual; codeteam reports this only once.", ride=True)

    def backup_branches(self):
        """Every branch to mirror on GitHub: the lane branches, exchange and integration, and any other
        branch checked out in one of the team's worktrees (work in progress). Never the base (shipped by
        the session that owns shipping), other teams' pins, or request leads' worktree-* branches."""
        from .team import v1
        t = self.team.t
        repo = str(t.repo)
        heads = v1.git(repo, "for-each-ref", "--format=%(refname:short)", f"refs/heads/{t.prefix}",
                       check=False).stdout.split()
        heads += [b for b in (t.exchange, t.integration) if b]
        wt = v1.git(repo, "worktree", "list", "--porcelain", check=False).stdout
        heads += [l.split("refs/heads/", 1)[1] for l in wt.splitlines() if l.startswith("branch refs/heads/")]
        out = []
        for b in heads:
            if b.startswith("pin/"):
                continue        # another team's read-only pin of this repo: theirs, not this team's work
            if b.startswith("land/"):
                continue        # codeteam-land's landing tree: reset to integration for every landing
            if b.startswith("worktree-"):
                continue        # a request lead's branch: its work reaches GitHub through the lane once accepted,
                                # and Time Machine holds it meanwhile (2026-10-28: these piled up on GitHub)
            if b and b != t.base and b not in out and v1.git(repo, "rev-parse", "--verify", "-q",
                                                              f"refs/heads/{b}", check=False).returncode == 0:
                out.append(b)
        return out

    def backup(self, st, now):
        """Every backup_min (60), push the team's branches to GitHub in one background push, so each
        coordinator's commits are off the machine within the hour even when no codeteam command moved them
        (2026-10-27: 12 of one team's lane branches were 2 to 167 commits ahead of GitHub). v1's rules apply:
        nothing when backup is off or there is no origin, force (the machine is the source of truth)."""
        every = getattr(self.team, "backup_min", 0)
        t = getattr(self.team, "t", None)
        if not every or not t or not getattr(t, "backup", False):
            return
        meta = st.setdefault("_backup", {})
        if now - (meta.get("at") or 0) < every * 60:
            return
        meta["at"] = now
        try:
            from .team import v1
            if v1.git(str(t.repo), "remote", "get-url", "origin", check=False).returncode:
                return
            branches = self.backup_branches()
            if not branches:
                return
            import subprocess
            logf = open(self.team.dir / "backup.log", "a")
            logf.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} push {len(branches)} branch(es)\n")
            logf.flush()
            subprocess.Popen(["git", "-C", str(t.repo), "push", "--force", "origin",
                              *[f"refs/heads/{b}:refs/heads/{b}" for b in branches]],
                             stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
            self.log(f"backup: pushing {len(branches)} branch(es) to GitHub in the background (team/v2/backup.log)")
        except Exception as e:      # a backup must never stop the loop
            self.log(f"backup skipped: {type(e).__name__}: {e}")

    def patrol(self, status, st, now):
        """v1's patrol checks (idle or asleep lanes with queued requests, dead leads, serial leads,
        branches outside the rule), every patrol_min. New findings ride along with the orchestrator's
        next prompt and show on the board at once; they never wake it."""
        every = getattr(self.team, "patrol_min", 0)
        if not every:
            return
        meta = st.setdefault("_patrol", {})
        if now - (meta.get("at") or 0) < every * 60:
            return
        meta["at"] = now
        try:
            lines = patrol_mod.findings(self.team, status, st, self.store, now)
        except Exception as e:      # a patrol must never stop the loop
            self.log(f"patrol skipped: {type(e).__name__}: {e}")
            return
        new = patrol_mod.record(self.team.dir / "patrol.json", lines, now)
        if not new:
            return
        # Work that has stopped wakes the orchestrator (2026-11-09: "yes wake it"); the rest still rides along
        # with its next prompt.
        wake = [x for x in new if any(w in x for w in patrol_mod.WAKES)]
        rest = [x for x in new if x not in wake]
        if wake:
            self.store.add("general", "codeteam", "REQUEST", self.team.t.orc_name(), "orc",
                           "PATROL (codeteam): work has stopped and nothing is waking it. Act on each line now. "
                           + " | ".join(wake[:12])
                           + (f" | and {len(wake) - 12} more: {self.team.dir / 'patrol.json'}" if len(wake) > 12 else ""))
            self.log(f"patrol: {len(wake)} finding(s) of stopped work sent to the orchestrator now")
        if rest:
            self.store.add("general", "codeteam", "REQUEST", self.team.t.orc_name(), "orc",
                           patrol_mod.TEXT + " | ".join(rest), ride=True)
            self.log(f"patrol: {len(rest)} new finding(s), riding along with the orchestrator's next prompt")
        dead = [x for x in new if "DEAD LEAD" in x]
        if dead:
            self.herdr.notify(f"codeteam {self.team.product}: a request lead died", "; ".join(dead)[:300])

    def show_in_herdr(self, obs, waiting_n, st):
        """herdr's sidebar shows each pane as `Coord-alpha` with its waiting mail (waiting_n: key -> count of
        queued and held messages) and why it is held ("agent view" while its pane shows a subagent's view,
        "typing" while its input box holds unsent text; tick clears both while the session is not running),
        so a person attached to herdr sees the team as codeteam sees it. Only sent when it changes."""
        for s in self.team.sessions():
            pane = obs.get(s.key, (None, None))[1]
            if not pane:
                continue
            n = waiting_n.get(s.key, 0)
            rec = st.setdefault(s.key, {})
            held = "agent view" if rec.get("view_since") else "typing" if rec.get("draft_since") else ""
            want = f"{s.display}|{n}|{held}"
            if rec.get("shown") == want and rec.get("shown_pane") == pane:
                continue
            try:
                self.herdr.pane_metadata(pane, "codeteam2", display=s.display, tokens={"mail": n or "", "hold": held})
                rec.update({"shown": want, "shown_pane": pane})
            except HerdrError as e:
                self.log(f"metadata {s.display}: {e}")

    def manifest_mtime(self):
        try:
            return os.path.getmtime(self.team.manifest)
        except (OSError, AttributeError, TypeError):
            return None

    def reload(self):
        try:
            new = type(self.team)(self.team.manifest)
            new.render_roles()
        except (Exception, SystemExit) as e:   # a half-saved or (to this loop's code) invalid manifest: keep
            # the old one. SystemExit too: v1's Team exits on a bad manifest, and that stopped a team's loop
            # (2026-10-27: a manifest only newer code accepts). Restarting the loop loads newer code.
            self.log(f"manifest changed but could not be read ({type(e).__name__}: {e}); keeping the previous one "
                     f"(if codeteam itself changed, restart the loop: Ctrl-C in its pane, then codeteam2 ensure-loop)")
            return
        self.team = new
        self.log("manifest changed: read again, role files re-rendered; sessions started from now on use it")

    def loop_alive(self):
        """True when a loop holds this team's lock (the heartbeat alone misleads right after a restart)."""
        try:
            with open(self.team.dir / "run.lock", "a") as f:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f, fcntl.LOCK_UN)
                return False
        except BlockingIOError:
            return True

    def run(self, once=False):
        lock = open(self.team.dir / "run.lock", "w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("codeteam2 run: another loop is already running for this team")
        self.herdr.ensure_server(str(self.team.dir / "herdr-server.log"))
        last = None
        seen_mtime = self.manifest_mtime()
        quick = 0
        while True:
            try:
                self.waited = 0
                # The manifest changed (an agent, a model, a window): read it again and re-render the role
                # files, so the next session started gets it. The loop read it once before (2026-10-27:
                # a team's new agents sat unused in a loop started three hours earlier).
                m = self.manifest_mtime()
                if m != seen_mtime:
                    seen_mtime = m
                    self.reload()
                acts, status = self.tick()
                line = " ".join(f"{k}={v}" for k, v in sorted(status.items()))
                # Logged when it changes: a delivery held tick after tick (someone typing, or a subagent's view shown) is said once.
                if (line, repr(acts)) != last:
                    self.log(f"state: {line}" + (f" | actions: {acts}" if acts else ""))
                    last = (line, repr(acts))
                # Replace after writing so readers don't see truncation; the new mtime lets the watchdog track freshness.
                tmp = self.team.dir / "heartbeat.tmp"
                tmp.write_text(str(int(ts())))
                tmp.replace(self.team.dir / "heartbeat")
            except Exception as e:      # the loop keeps going; the error is logged
                self.log(f"tick error: {type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}")
            if once:
                return
            if self.waited > 0 and quick < REACT_MAX:
                quick += 1
                time.sleep(min(REACT_S, self.team.poll_s))
            else:
                quick = 0
                time.sleep(self.team.poll_s)
