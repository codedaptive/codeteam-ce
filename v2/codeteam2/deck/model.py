"""What the snapshot means: the flags on each session and subagent, and the alerts, derived from plain dicts.

No I/O and no clock: every function takes `now`, so a fixture snapshot gives the same answer in a test as live.
"""

# Seconds and GB. stall_s is the watch-agent rule (12 minutes without a transcript write); child_grace_s keeps a
# child that finished a moment after its parent's last write from counting as something the parent should have seen.
THRESHOLDS = {"stall_s": 720, "blocked_alert_s": 120, "heartbeat_red_s": 60, "disk_red_gb": 50,
              "build_out_alert_gb": 10, "child_grace_s": 30}
# The folders of a worktree that hold build output.
BUILD_PARTS = ("cargo-target", "target", ".build")


def _status(sess):
    return (sess.get("herdr") or {}).get("status")


def _finished_after(children, last_write, th):
    """True when a finished child wrote more than the grace period after its parent's last write."""
    return any(c.get("finished") and c["last_write"] > last_write + th["child_grace_s"] for c in children)


def session_flags(sess, now, th):
    """The session's own flags. waiting_on_finished_child looks at its depth-1 subagents (those with no parent
    agent), against the transcript's last write; an exited session waits for nothing."""
    since = (sess.get("herdr") or {}).get("since")
    blocked = _status(sess) == "blocked"
    mtime = sess.get("transcript_mtime")
    children = [a for a in sess.get("agents") or [] if a.get("parent") is None]
    return {"between_turns": _status(sess) == "working" and sess.get("transcript_state") == "ended",
            "blocked": blocked, "blocked_for_s": now - since if blocked and since is not None else None,
            "held": ((sess.get("mail") or {}).get("held") or 0) > 0,
            "typing": bool(sess.get("draft_since")), "api_error": bool(sess.get("api_error")),
            "waiting_on_finished_child": _status(sess) != "absent" and sess.get("transcript_state") == "ended"
            and mtime is not None and _finished_after(children, mtime, th)}


def agent_flags(agent, agents, sess, ps_by_worktree, now, th):
    """stalled: silent for stall_s with no build process in its worktree (the agent's, else its session's), and never
    when ps_by_worktree is None: with no process list the deck cannot tell, so it assumes the agent is alive.
    waiting on a finished child: its turn ended and a child finished after its last write. orphan: still writing while its
    session has exited."""
    live = not agent["finished"]
    silent = now - agent["last_write"] >= th["stall_s"]
    worktree = agent.get("worktree") or sess.get("worktree") or sess.get("cwd")
    children = [a for a in agents if a.get("parent") == agent["id"]]
    return {"stalled": live and silent and ps_by_worktree is not None and not ps_by_worktree.get(worktree),
            "waiting_on_finished_child": live and agent.get("last_state") == "ended"
            and _finished_after(children, agent["last_write"], th),
            "orphan": live and not silent and _status(sess) == "absent"}


def _age(seconds):
    seconds = int(seconds)
    return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m" if seconds >= 3600 else \
        f"{seconds // 60}m{seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"


def _alert(kind, team, session, subject, text, since):
    return {"key": f"{kind}:{team or ''}:{subject}", "kind": kind, "team": team, "session": session,
            "text": text, "since": since}


def _agent_alerts(team, sess, now):
    out = []
    for agent in sess.get("agents") or []:
        flags = agent.get("flags") or {}
        who = f"{sess.get('name')}/{agent.get('type') or 'agent'} {agent.get('description') or ''}".strip()
        if flags.get("stalled"):
            out.append(_alert("stalled", team, sess.get("name"), agent["id"],
                              f"{who} silent {_age(now - agent['last_write'])}", agent["last_write"]))
        if flags.get("waiting_on_finished_child"):
            out.append(_alert("child_finished", team, sess.get("name"), agent["id"],
                              f"{who} waits on a finished child", now))
    return out


def _session_alerts(team, sess, now, th):
    flags, name = sess.get("flags") or {}, sess.get("name")
    out = []
    blocked_for = flags.get("blocked_for_s")
    if blocked_for is not None and blocked_for >= th["blocked_alert_s"]:
        out.append(_alert("blocked", team, name, name, f"{name} blocked {_age(blocked_for)}", now - blocked_for))
    if flags.get("held"):
        mail = sess.get("mail") or {}
        oldest = mail.get("oldest_waiting_s")
        out.append(_alert("held", team, name, name, f"{name} has {mail.get('held')} held message(s)",
                          now if oldest is None else now - oldest))
    if flags.get("waiting_on_finished_child"):
        out.append(_alert("child_finished", team, name, name, f"{name} waits on a finished child", now))
    return out + _agent_alerts(team, sess, now)


def _team_alerts(team, now, th):
    name = team.get("name")
    out = []
    beat = team.get("heartbeat_age_s")
    if team.get("state") == "up" and beat is not None and beat > th["heartbeat_red_s"]:
        out.append(_alert("heartbeat", name, None, "loop", f"{name} loop heartbeat {_age(beat)} old", now))
    if team.get("cap") is not None and team.get("lanes_running", 0) > team["cap"]:
        out.append(_alert("over_cap", name, None, "cap",
                          f"{name} has {team['lanes_running']} lanes awake over its cap of {team['cap']}", now))
    for wt in (team.get("disk") or {}).get("worktrees", []):
        gb = sum((wt.get("parts") or {}).get(p, 0) for p in BUILD_PARTS)
        if gb > th["build_out_alert_gb"]:
            out.append(_alert("build_output", name, None, wt["path"], f"{wt['path']} build output {gb:.1f} GB", now))
    for sess in team.get("sessions", []):
        out += _session_alerts(name, sess, now, th)
    return out


def alerts(snap, now, th):
    """Every condition that holds now, newest first (by since); key = kind + team + session, agent or path."""
    out = []
    free = (snap.get("volume") or {}).get("free_gb")
    if free is not None and free < th["disk_red_gb"]:
        out.append(_alert("disk_low", None, None, "volume", f"free disk {free:.0f} GB", now))
    for team in snap.get("teams", []):
        out += _team_alerts(team, now, th)
    return sorted(out, key=lambda a: -a["since"])


def derive(snap, now, thresholds=None):
    """Set every session's and subagent's flags and the snapshot's alerts, in place; returns the snapshot.
    thresholds override THRESHOLDS key by key."""
    th = {**THRESHOLDS, **(thresholds or {})}
    procs = (snap.get("builds") or {}).get("procs", {})
    for team in snap.get("teams", []):
        for sess in team.get("sessions", []):
            sess["flags"] = session_flags(sess, now, th)
            for agent in sess.get("agents") or []:
                agent["flags"] = agent_flags(agent, sess["agents"], sess, procs, now, th)
    snap["alerts"] = alerts(snap, now, th)
    return snap


class AlertLog:
    """The alerts of one deck session: one line per key, kept after its condition clears, with the time it was
    first seen."""

    def __init__(self):
        self._seen = {}

    def update(self, current, now):
        for alert in current:
            self._seen.setdefault(alert["key"], {**alert, "since": alert.get("since", now)})
        return sorted(reversed(list(self._seen.values())), key=lambda a: -a["since"])
