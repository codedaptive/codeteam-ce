"""The loop's hung-request watchdog: one pass over every session and its recent subagents.

On 2026-11-19 the proxy recovered from an outage but 18 subagents sat on model requests that never returned
. A main session whose request has waited past its model's threshold gets Esc, then `continue`; a
subagent's parent gets a NOTE at twice the threshold, since only the parent can stop and restart it. Each hang is
acted on once, and every action goes through watch_record. Subagent transcripts are the `agent-*.jsonl` files at
any depth under the session's `subagents/` folder: workflow agents sit in `subagents/workflows/wf_<id>/`, beside
the workflow's own journal, which is not an agent and is not read. A session whose transcript cannot be read is
logged and skipped, so the others are still watched.

`continue` is typed through rt.transport.deliver, not Runtime.deliver: it is no stored mail, so it has no id for
awaiting_turn and redeliver to track.
"""
import json
from pathlib import Path

from .hang_action import hang_action
from .herdr import HerdrError
from .pending_request import pending_request
from .transcript_records import transcript_records
from .transport import Refused
from .watch_record import watch_record

EVERY_S = 30                # transcripts are re-read at most this often; a threshold is minutes, so 30 s is prompt
SUBAGENT_WINDOW_S = 7200    # a subagent file untouched for 2 h belongs to work long gone; its last request is history
NOTED_MAX = 200             # request ids remembered for subagent NOTEs; older hangs have ended or been noted


def hang_watch_pass(rt, status, st, now: float) -> None:
    meta = st.setdefault("_hangwatch", {})
    if now - (meta.get("at") or 0) < EVERY_S:
        return
    meta["at"] = now
    overrides = getattr(rt.team, "cfg", {}).get("hang_threshold_s")
    for s in rt.team.sessions():
        if status.get(s.key, "absent") == "absent":
            continue
        try:
            _watch_session(rt, status, st, meta, s, now, overrides)
        except Exception as e:      # one session's bad transcript must not keep the watchdog from the rest
            rt.log(f"hangwatch {s.display}: {type(e).__name__}: {e}")


def _watch_session(rt, status, st, meta, s, now, overrides):
    path = rt.transcript(st.setdefault(s.key, {}))
    if not path:
        return
    if status[s.key] == "working":
        _nudge_main(rt, s, st, meta, path, now, overrides)
    for sub in _recent_subagents(Path(path), now):
        _note_subagent(rt, s, meta, sub, now, overrides)


def _nudge_main(rt, s, st, meta, path, now, overrides):
    pending = pending_request(transcript_records(path))
    acted = meta.setdefault("acted", {})
    if hang_action("main", pending, now, overrides) != "nudge" or acted.get(s.key) == pending["id"]:
        return
    if rt.screen_hold(s, st) is not None:
        return
    acted[s.key] = pending["id"]
    try:
        rt.herdr.agent_send_keys(s.agent, "esc")
        rt.transport.deliver(s.agent, "continue")
    except (Refused, HerdrError) as e:
        rt.log(f"hangwatch {s.display}: Esc+continue failed: {type(e).__name__}: {e}")
        return
    _record(rt, s, None, None, pending, now, "esc+continue")


def _recent_subagents(path, now):
    for sub in sorted((path.with_suffix("") / "subagents").rglob("agent-*.jsonl")):
        try:
            if now - sub.stat().st_mtime <= SUBAGENT_WINDOW_S:
                yield sub
        except OSError:     # removed between the listing and the stat
            continue


def _note_subagent(rt, s, meta, sub, now, overrides):
    info = _meta(sub.with_suffix(".meta.json"))
    if info.get("finished"):
        return
    pending = pending_request(transcript_records(sub))
    noted = meta.setdefault("noted", [])
    if hang_action("subagent", pending, now, overrides) != "note" or pending["id"] in noted:
        return
    meta["noted"] = (noted + [pending["id"]])[-NOTED_MAX:]
    agent = sub.stem.removeprefix("agent-")
    agent_type = info.get("agentType", "unknown")
    rt.store.add("general", "codeteam", "NOTE", s.display, s.key,
                 f"{agent} ({agent_type}, {pending['model']}) has waited {int(now - pending['at']) // 60} min on a "
                 f"model request: TaskStop it and start it again on its own tree")
    _record(rt, s, agent, agent_type, pending, now, "note parent")


def _meta(path):
    """The subagent's .meta.json; {} when it is missing or half written (Claude Code writes it as the agent runs)."""
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _record(rt, s, agent, agent_type, pending, now, action):
    watch_record(rt.team.dir, rt.log, {"at": now, "session": s.display, "agent": agent, "agent_type": agent_type,
                                       "model": pending["model"], "wait_s": int(now - pending["at"]),
                                       "action": action, "request": pending["id"]})
