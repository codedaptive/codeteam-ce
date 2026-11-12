"""codeteam2: codeteam's runtime on herdr.

    codeteam2 up <manifest>                 the team's herdr workspace, roles, the staff, the loop
    codeteam2 run <manifest> [--once]       the loop (normally in the workspace's daemon pane)
    codeteam2 say <manifest> <channel> <sender> <TYPE> <to> <text...>
                                            send a message (v1's signature, so role files keep working)
    codeteam2 watch <manifest> <name> [--now]   messages for a session that are not delivered yet
    codeteam2 await <manifest> <lane> <feature>   record that the lane waits for a feature (v1's wait record);
                                            push-up of that feature sends the lane a NOTE
    codeteam2 launch <manifest> <name...>   start sessions now (the loop also starts them for mail)
    codeteam2 sleep <manifest> <name>       end a session (/exit) when it is idle
    codeteam2 status <manifest>             every session's real state and its mail
    codeteam2 tail <manifest>               follow the team's messages live
    codeteam2 compact-now <manifest> <name> [transcript]   /compact, then the resume line, when idle
    codeteam2 drop <manifest> <id...> [--note TEXT]   take messages out of the queue (kept on record): queued,
                                            held, or prompted and still awaiting their turn; says per id,
                                            exits 1 when any id was not dropped
    codeteam2 ensure-loop <manifest>        start herdr's server and the loop if the team is up and they are not
                                            (run every minute by v1's cron wake for a team on v2)
    codeteam2 down <manifest> [--close]     end every session; --close removes the workspace

Everything else (unit, squash, push-up, integrate, promote, sweep, ...) is codeteam v1's.
"""
import argparse
import datetime as dt
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from .herdr import HerdrError
from .scheduler import READY, Runtime, last_mids
from .store import RUNTIME
from .team import CODETEAM2, OWNER, WORKSPACE, Team, v1

TYPES = ("REQUEST", "ANSWER", "NOTE", "STATUS", "BUG", "PUSHED", "DONE", "RULING", "READY")


LOG_MAX = 10 * 1024 * 1024       # codeteam2.log is moved to codeteam2.log.1 at this size


def logger(team):
    path = team.dir / "codeteam2.log"

    def log(msg):
        line = f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
        print(line, flush=True)
        try:
            if path.exists() and path.stat().st_size > LOG_MAX:
                path.replace(path.with_name(path.name + ".1"))
        except OSError:
            pass
        with path.open("a") as f:
            f.write(line + "\n")
    return log


def cmd_up(team, rt, a):
    log = logger(team)
    marker = team.dir / "up"          # the team is meant to be up until `down` (the plugin's autostart reads it)
    if a.if_was_up and not marker.exists():
        print(f"{team.product}: was not up; left down")
        return
    marker.write_text(dt.datetime.now().isoformat(timespec="seconds") + "\n")
    (team.dir / "down").unlink(missing_ok=True)     # the loop may start and deliver again
    started = rt.herdr.ensure_server(str(team.dir / "herdr-server.log"))
    log(f"herdr session {team.herdr_session}: {'started' if started else 'running'}")
    team.render_roles()
    log(f"session folders approved: {team.approve_dirs()}")
    ws = rt.workspace()
    log(f"workspace {team.product}: {ws}")
    st = team.load_state()
    obs = rt.observe(ws)
    if team.halted():
        targets = []          # the user's stop: nothing starts until team/HALTED is removed
        log(f"{team.product} is HALTED ({team.t.home / 'HALTED'}): no session starts and the loop types "
            f"nothing until that file is removed")
    elif a.loop_only:
        targets = []          # nothing starts now; sessions start when mail comes for them
    elif a.targets:
        targets = a.targets   # named: started even if held (the user asked for them)
    else:
        targets = [s.key for s in team.sessions() if s.kind == "staff" and not team.held(s.key)]
        for s in team.sessions():
            if s.kind == "staff" and team.held(s.key):
                log(f"{s.display}: held (team/held/{s.key}); not started")
    for name in targets:
        s = team.session(name)
        if not s:
            sys.exit(f"unknown session {name}")
        if obs.get(s.key, ("absent",))[0] == "absent":
            rt.start(s, st, resume=a.resume and bool(st.get(s.key, {}).get("sid")))
        else:
            log(f"{s.display}: already running ({obs[s.key][0]})")
    if not a.no_loop:
        pane, new = rt.ensure_daemon_pane(ws)
        if new or not rt.loop_alive():
            rt.herdr.pane_run(pane, f"{CODETEAM2} run {team.t.manifest}")
            log(f"loop started in pane {pane}")
        else:
            log(f"loop running in pane {pane}")


def cmd_run(team, rt, a):
    rt.log = logger(team)
    rt.run(once=a.once)


def cmd_ensure_loop(team, rt, a):
    """For cron (v1's wake calls it every minute for a team on v2): if the team is up, make sure herdr's
    server and the team's loop are running. After a reboot, starting the server needs the owner's login
    session (launchd's gui/<uid> domain); the plugin's startup hook tries to bring back configured
    autostart teams that were up, but an up can fail or time out."""
    if not (team.dir / "up").exists() or (team.dir / "down").exists():
        return
    log = logger(team)
    if rt.herdr.ensure_server(str(team.dir / "herdr-server.log")):
        log(f"ensure-loop: herdr session {team.herdr_session} was not running; started")
        time.sleep(3)               # the plugin's startup hook may bring the loop back itself
    if rt.loop_alive():
        return
    ws = rt.workspace()
    pane, _ = rt.ensure_daemon_pane(ws)
    if not rt.loop_alive():
        rt.herdr.pane_run(pane, f"{CODETEAM2} run {team.t.manifest}")
        log(f"ensure-loop: the loop was not running; started in pane {pane}")


def cmd_drop(team, rt, a):
    """Drop messages by id, one line per distinct id (a repeated id counts once), exit 1 when any was not
    dropped. A message prompted and still
    awaiting its turn (in a session's last_mids with awaiting_turn) is dropped too, and taken out of that
    session's state so the loop does not put it back. The loop may save an older state over this one; its
    redeliver leaves a message that is no longer delivered, so the drop holds either way."""
    ids = list(dict.fromkeys(int(x.lstrip("#")) for x in a.ids))      # de-duplicated, order kept
    st = team.load_state()
    recs = [r for r in st.values() if isinstance(r, dict) and r.get("awaiting_turn")]
    awaiting = {mid for r in recs for mid in last_mids(r)}
    got = rt.store.drop(ids, a.note or "dropped by hand", awaiting=awaiting)
    for mid in ids:
        print(f"#{mid} dropped (kept on record in the store)" if got[mid] == "dropped" else f"#{mid} {got[mid]}")
    gone = {mid for mid, r in got.items() if r == "dropped"}
    changed = False
    for r in recs:
        left = [mid for mid in last_mids(r) if mid not in gone]
        if len(left) == len(last_mids(r)):
            continue
        r.update({"last_mids": left, "last_mid": None})
        if not left:
            r["awaiting_turn"] = False
        changed = True
    if changed:
        team.save_state(st)
    if len(gone) < len(ids):
        sys.exit(1)


def other_team(team, name, kind):
    """The manifest of another team when a message names it: `Orc-<Product>` (any kind), or `codeteam` / `Orc-Codeteam`
    with a REQUEST from a product team (process requests go to team codeteam). None otherwise.
    Problem 11 (2026-11-08): such mail stayed in the sender's own store, where nobody read it."""
    low = name.strip().lower()
    if low == "codeteam":
        prod = "codeteam" if kind == "REQUEST" else None
    elif low.startswith("orc-"):
        prod = low[4:]
    else:
        prod = None
    if not prod or prod == str(team.product).lower():
        return None
    m = Path(team.manifest).parent / f"{prod}.toml"
    return m if m.exists() else None


def forward(team, rt, a, kind, name, manifest, text):
    """Hand the message to the other team's own store (its orchestrator), and record it here as forwarded."""
    import subprocess
    r = subprocess.run([str(CODETEAM2), "say", str(manifest), "general", a.sender, kind, "orc",
                        f"[from team {team.product}] {text}"], capture_output=True, text=True, timeout=120)
    mid = rt.store.add(a.channel, a.sender, kind, name, "codeteam", text)
    rt.store.mark(mid, "delivered", f"forwarded to {manifest.stem}" if r.returncode == 0 else
                  f"forward to {manifest.stem} failed: {(r.stderr or r.stdout).strip()[:200]}")
    team.mirror_to_channel_log(a.channel, a.sender, kind, name, text)
    print(f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M')} | #{mid} | {a.sender} | {kind} {name} -> team "
          f"{manifest.stem}{'' if r.returncode == 0 else ' (FAILED)'} | {text}")


CREATOR_INBOX = WORKSPACE / "team-codeteam" / "creator-inbox.log"


def for_creator(a, kind, name, text):
    """A message to `codeteam` or `creator` that is meant for codeteam's builder (the creator): every kind but the
    patrol's answers. It goes to one inbox file and a notice for the owner (without it, messages to the creator
    reached no one). True when it was taken."""
    if name.strip().lower() not in ("codeteam", "creator") or a.sender == "codeteam":
        return False
    if kind == "ANSWER" and not a.sender.startswith("Designer-") and "creator" not in text.lower():
        return False                # an answer to a patrol line or an idle check: recorded as before
    CREATOR_INBOX.parent.mkdir(parents=True, exist_ok=True)
    with open(CREATOR_INBOX, "a") as f:
        f.write(f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M')} | {a.sender} | {kind} | {' '.join(text.split())}\n")
    return True


def cmd_say(team, rt, a):
    kind = a.type.upper()
    if kind not in TYPES and kind != RUNTIME:
        sys.exit(f"type must be one of {', '.join(TYPES)}")
    text = " ".join(a.text)
    t = team.t
    # Another team (link:<team>) or an external assistant: v1's own post, which logs the channel and
    # drops the message in the recipient's inbox; a team on v2 takes it from there into its store
    # (2026-10-27: v2 had sent these to the sender's own orchestrator).
    ext = a.channel in t.assistants and not t.managed(a.channel)
    if a.channel.startswith("link:") or ext:
        other = a.channel[5:]
        if ext:
            ch = t.assistant_channel(a.channel)
        elif other in t.assistant_links(a.sender):
            ch = t.assistant_link_channel(a.sender, other)
        elif other in t.links:
            ch = t.link_channel(other)
        else:
            sys.exit(f"{a.channel}: no such link for {a.sender} (links: {', '.join(t.links) or 'none'})")
        print(v1.post(t, ch, a.sender, kind, a.to, " ".join(text.split())), end="")
        return
    if team.is_user(a.to):
        # For the owner: kept in the store and the log, shown by status, and a herdr notification.
        mid = rt.store.add(a.channel, a.sender, kind, a.to, "user", text)
        team.mirror_to_channel_log(a.channel, a.sender, kind, a.to, text)
        rt.store.mark(mid, "delivered", "for the user")
        rt.herdr.notify(f"codeteam {team.product}: {kind} from {a.sender}", text[:300])
        print(f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M')} | #{mid} | {a.sender} | {kind} {a.to} (for you) | {text}")
        return
    sender = team.session(a.sender)
    # Only the orchestrator messages everyone (sessions broadcast instead of talking to the one
    # they meant, and every broadcast cost every awake session a turn). From anyone else, `all` goes to the
    # orchestrator alone, who forwards it if it should go further.
    if any(n.strip().lower() == "all" for n in a.to.split(",")) and not (sender and sender.key == "orc"):
        orc = team.t.orc_name()
        print(f"codeteam: only {orc} messages everyone; this goes to {orc} alone. "
              f"To reach a session, name it: say ... <TYPE> <its name> \"<text>\"", file=sys.stderr)
        a.to = orc
    if a.to.strip().lower() == "all" and sender and sender.key == "orc":
        # The orchestrator's `all`: every other session that is awake gets it; it starts no one (a broadcast
        # waits for its session to be awake). Before 2026-10-30 v2 recorded it and delivered it to nobody.
        ids = []
        for s in team.sessions():
            if s.key == "orc":
                continue
            mid = rt.store.add(a.channel, a.sender, kind, "all", s.key, text)
            rt.store.mark(mid, "queued", "broadcast")
            ids.append(mid)
        team.mirror_to_channel_log(a.channel, a.sender, kind, "all", text)
        print(f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M')} | #{ids[0] if ids else '-'}..#{ids[-1] if ids else '-'} | "
              f"{a.sender} | {kind} all -> every awake session | {text}")
        return
    # TO may list several sessions (v1: `Nagatha,Kong`): one message each (found in the factory smoke run).
    names = [n.strip() for n in a.to.split(",") if n.strip()] or [a.to]
    targets = []
    for n in list(names):
        m = other_team(team, n, kind)
        if m:
            forward(team, rt, a, kind, n, m, text)
            names.remove(n)
    if not names:
        return
    for n in names:
        if for_creator(a, kind, n, text):
            mid = rt.store.add(a.channel, a.sender, kind, n, "codeteam", text)
            rt.store.mark(mid, "delivered", f"for the creator: {CREATOR_INBOX}")
            team.mirror_to_channel_log(a.channel, a.sender, kind, n, text)
            rt.herdr.notify(f"codeteam {team.product}: {kind} for the creator from {a.sender}", text[:300])
            print(f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M')} | #{mid} | {a.sender} | {kind} {n} -> the creator's "
                  f"inbox ({CREATOR_INBOX}) | {text}")
            continue
        if n.lower() == "codeteam":
            continue            # an answer to codeteam itself (an idle check): recorded, delivered to no session
        s = team.resolve_recipient(n, a.channel)
        if sender and s.key == sender.key:
            continue            # never the sender (v1's rule): a designer's "idle" came back to it
        if s.key not in [t.key for t in targets]:
            targets.append(s)
    if not targets:
        mid = rt.store.add(a.channel, a.sender, kind, a.to, "codeteam", text)
        rt.store.mark(mid, "delivered", "for codeteam; no session")
        team.mirror_to_channel_log(a.channel, a.sender, kind, a.to, text)
        print(f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M')} | #{mid} | {a.sender} | {kind} {a.to} (recorded) | {text}")
        return
    ids = []
    for s in targets:
        mid = rt.store.add(a.channel, a.sender, kind, a.to, s.key, text)
        ids.append(mid)
    team.mirror_to_channel_log(a.channel, a.sender, kind, a.to, text)   # exactly v1's line: v1 parses it (READY)
    print(f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M')} | #{','.join(map(str, ids))} | {a.sender} | {kind} {a.to} -> "
          f"{', '.join(t.display for t in targets)} | {text}")


def cmd_watch(team, rt, a):
    """v1's watch, for role files that still use it. Messages reach a session only as [codeteam]
    prompts from the loop: a request read in a tool's output is (rightly) treated by the model as
    untrusted, so watch never shows message text (found in the smoke run, 2026-10-24). With --now
    it says what is waiting; without it, it waits until something is, then says so."""
    s = team.session(a.name)
    if not s:
        sys.exit(f"unknown session {a.name}")
    deadline = time.time() + (float(a.timeout) if a.timeout else 3600)
    while True:
        rows = [m for m in rt.store.pending(s.key, held=True) if m["kind"] != RUNTIME]
        if rows or a.now or time.time() > deadline:
            break
        time.sleep(2)
    if rows:
        print(f"{len(rows)} message(s) waiting for {s.display}: " +
              ", ".join(f"#{m['id']} {m['kind']} from {m['sender']}" for m in rows) +
              ". codeteam v2 delivers each to you as a prompt beginning with [codeteam] as soon as your turn "
              "ends: end your turn to receive it.")
    else:
        print(f"nothing waiting for {s.display}. Messages arrive as prompts beginning with [codeteam]; "
              "no watcher is needed.")


def cmd_await(team, rt, a):
    """`await MANIFEST LANE FEATURE`: the line role files render from `{{cmd_await}} {{lane}} F`. It is v1's
    wait record (the lane's awaits file, which v1's push-up reads in tell_waiting_lanes to NOTE the lane), so
    it calls v1's cmd_await. The one-name form `await MANIFEST NAME` is the old watch alias, kept for any caller."""
    if a.feature:
        v1.cmd_await(team.t, SimpleNamespace(lane=a.name, feature=a.feature))
    else:
        cmd_watch(team, rt, a)


def cmd_launch(team, rt, a):
    """Staff start now. A lane is started by the loop, so the lane cap holds: launch only asks
    for it (--now starts it regardless)."""
    if team.halted():
        sys.exit(f"{team.product} is HALTED ({team.t.home / 'HALTED'}): remove that file to start sessions")
    (team.dir / "down").unlink(missing_ok=True)     # launching means the team is in use again
    st = team.load_state()
    obs = rt.observe(rt.workspace())
    names = [s.key for s in team.sessions()] if a.targets in (["all"], ["lanes"]) else a.targets
    if a.targets == ["lanes"]:
        names = [s.key for s in team.sessions() if s.kind == "lane"]
    if a.targets == ["staff"]:          # v1's `launch staff` (the orchestrator's role file uses it)
        names = [s.key for s in team.sessions() if s.kind == "staff" and s.key != "orc" and not team.held(s.key)]
    for name in names:
        s = team.session(name)
        if not s:
            sys.exit(f"unknown session {name}")
        if obs.get(s.key, ("absent",))[0] != "absent":
            print(f"{s.display}: already running")
            continue
        if s.kind == "lane" and not a.now:
            team.update_state(s.key, {"wake_requested": time.time()})
            print(f"{s.display}: asked for; the loop starts it within the lane cap ({team.cap})")
            continue
        rt.start(s, st, resume=a.resume and bool(st.get(s.key, {}).get("sid")))


def cmd_sleep(team, rt, a):
    s = team.session(a.name)
    if not s:
        sys.exit(f"unknown session {a.name}")
    st = team.load_state()
    status = rt.observe(rt.workspace()).get(s.key, ("absent",))[0]
    if status == "absent":
        print(f"{s.display}: not running")
    elif status in READY or a.force:
        if not rt.stop(s, st):
            print(f"{s.display}: not ended (unsent text in its input box, its pane shows a subagent's view, or herdr refused); try again")
        team.save_state(st)
    else:
        print(f"{s.display} is {status}; it is ended once idle (or use --force)")


def cmd_status(team, rt, a):
    ws = rt.workspace(create=False)
    obs = rt.observe(ws) if ws else {}
    counts = rt.store.counts()
    st = team.load_state()
    now = time.time()
    # A non-atomic writer or damaged file can leave no valid timestamp; omit the beat in that case.
    try:
        age = now - int((team.dir / "heartbeat").read_text().strip())
    except (OSError, ValueError):
        age = None
    print(f"codeteam2 {team.product}: herdr session {team.herdr_session}, workspace {ws or '-'}, "
          f"loop {'alive' if rt.loop_alive() else 'NOT RUNNING'}"
          f"{f' (beat {int(age)}s ago)' if age is not None else ''}, lane cap {team.cap}"
          f"{'  HALTED: starts and types nothing' if team.halted() else ''}")
    print(f"  {'session':22} {'state':9} {'for':>6}  {'waiting':>7} {'delivered':>9}  pane")
    for s in team.sessions():
        status, pane = obs.get(s.key, ("absent", None, None))[:2]
        since = st.get(s.key, {}).get("state_since")
        dur = f"{int((now - since) / 60)}m" if since else ""
        c = counts.get(s.key, {})
        rec = st.get(s.key, {})
        notes = []
        if team.held(s.key):
            notes.append("HELD")
        # Only for a session herdr shows running: the state file can be stale while the loop is down.
        if status != "absent" and rec.get("draft_since"):
            notes.append(f"TYPING {int((now - rec['draft_since']) / 60)}m (mail held)")
        if status != "absent" and rec.get("view_since"):
            notes.append(f"SHOWS {rec.get('view')}'s VIEW {int((now - rec['view_since']) / 60)}m (mail held)")
        if rec.get("api_error"):
            notes.append(f"API ERROR: {rec['api_error'][:60]}")
        print(f"  {s.display:22} {status:9} {dur:>6}  {c.get('queued', 0) + c.get('held', 0):>7} "
              f"{c.get('delivered', 0):>9}  {pane or '-'}{'  ' + '; '.join(notes) if notes else ''}")
    from .patrol import latest
    at, lines = latest(team.dir / "patrol.json")
    if lines:
        print(f"  patrol ({int((now - at) / 60)} min ago):")
        for x in lines[:8]:
            print(f"    {x[:160]}")
    mine = [m for m in rt.store.recent(limit=200) if m["target"] == "user"][-3:]
    if mine:
        print("  for you (latest):")
        for m in mine:
            print(f"    #{m['id']} {m['ts'][11:16]} {m['kind']} from {m['sender']}: {' '.join(m['body'].split())[:150]}")


def cmd_tail(team, rt, a):
    """Follow the team's messages as they come (Ctrl-C to stop)."""
    seen = 0
    for m in rt.store.recent(limit=a.lines):
        print(f"{m['ts'][11:16]} #{m['id']} {m['sender']} -> {m['recipient']} {m['kind']}: {' '.join(m['body'].split())[:220]}", flush=True)
        seen = m["id"]
    while True:
        time.sleep(2)
        for m in rt.store.after(seen):
            print(f"{m['ts'][11:16]} #{m['id']} {m['sender']} -> {m['recipient']} {m['kind']}: "
                  f"{' '.join(m['body'].split())[:220]}", flush=True)
            seen = m["id"]


def cmd_compact_now(team, rt, a):
    s = team.session(a.name)
    if not s:
        sys.exit(f"unknown session {a.name}")
    rt.store.add("runtime", "codeteam", RUNTIME, s.display, s.key,
                 "/compact Keep the Refocus report and the handoff above verbatim as the working state. "
                 "Summarize everything before them in a few lines.")
    rt.store.add("runtime", "codeteam", RUNTIME, s.display, s.key,
                 "Compaction done. Do steps 1-3 of .claude/commands/recover-from-compact.md (find your handoff, walk "
                 "back if needed, check the repo), then carry on with the work in progress.")
    print(f"{s.display}: /compact and the resume line queued; the loop sends them when it is idle")


def cmd_down(team, rt, a):
    (team.dir / "up").unlink(missing_ok=True)
    (team.dir / "down").write_text(dt.datetime.now().isoformat(timespec="seconds") + "\n")   # the loop stops acting
    time.sleep(team.poll_s + 0.5)        # let a tick already under way finish before the /exits go out
    ws = rt.workspace(create=False)
    if not ws:
        print("no workspace")
        return
    obs = rt.observe(ws)
    st = team.load_state()
    for s in team.sessions():
        if obs.get(s.key, ("absent",))[0] != "absent":
            if not rt.stop(s, st):
                print(f"{s.display}: left running (unsent text in its input box, or herdr refused /exit)")
    if a.close:
        time.sleep(3)
        rt.herdr.workspace_close(ws)
        print(f"workspace {ws} closed")


def cmd_halt(team, rt, a):
    """Shut the team down and keep it down (one command for it): write team/HALTED, send every
    session /exit, answer Claude Code's "Background work is running" with "Exit and stop tasks", and after
    --grace seconds interrupt a session still mid-turn (Esc, then /exit). Waits up to --wait seconds and says
    who is left. `codeteam2 unhalt` undoes it."""
    from types import SimpleNamespace
    halted = team.t.home / "HALTED"
    halted.write_text(a.reason or f"Halted by {OWNER} {dt.datetime.now():%Y-%m-%d %H:%M} (codeteam2 halt). "
                      "Remove this file, or run codeteam2 unhalt, to let the team start again.\n")
    print(f"{team.product}: HALTED ({halted})")
    cmd_down(team, rt, SimpleNamespace(close=False))
    start, nudged = time.time(), set()
    while True:
        ws = rt.workspace(create=False)
        obs = rt.observe(ws) if ws else {}
        left = [s for s in team.sessions() if obs.get(s.key, ("absent",))[0] != "absent"]
        if not left:
            print(f"{team.product}: every session has exited")
            return
        if time.time() - start > a.wait:
            print(f"{team.product}: still running after {a.wait} s: "
                  + ", ".join(f"{s.display} ({obs[s.key][0]})" for s in left))
            sys.exit(1)
        for s in left:
            try:
                screen = rt.herdr.agent_read(s.agent, lines=15)
            except Exception:
                screen = ""
            if "Exit and stop tasks" in screen:
                rt.herdr.agent_send_keys(s.agent, "enter")
                print(f"{s.display}: background work stopped, exiting")
            elif obs[s.key][0] == "working" and time.time() - start > a.grace and s.key not in nudged:
                nudged.add(s.key)
                rt.herdr.agent_send_keys(s.agent, "esc")
                time.sleep(1)
                try:
                    rt.herdr.agent_prompt(s.agent, "/exit")
                except Exception:
                    pass
                print(f"{s.display}: interrupted mid-turn, exiting")
        time.sleep(5)


def cmd_unhalt(team, rt, a):
    """Bring a halted team back: remove team/HALTED and start its standing sessions where they left off
    (codeteam2 up --resume). Lanes start as mail reaches them."""
    from types import SimpleNamespace
    (team.t.home / "HALTED").unlink(missing_ok=True)
    print(f"{team.product}: unhalted")
    cmd_up(team, rt, SimpleNamespace(if_was_up=False, loop_only=False, targets=a.targets, resume=True, no_loop=False))


def main(argv=None):
    if (sys.argv[1:] if argv is None else list(argv))[:1] == ["deck"]: from .deck.app import main as deck; return deck((sys.argv[1:] if argv is None else list(argv))[1:])
    ap = argparse.ArgumentParser(prog="codeteam2", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def p(name):
        sp = sub.add_parser(name)
        sp.add_argument("manifest")
        return sp
    sp = p("up"); sp.add_argument("targets", nargs="*"); sp.add_argument("--no-loop", action="store_true")
    sp.add_argument("--resume", action="store_true", help="resume the staff sessions codeteam2 last ran")
    sp.add_argument("--loop-only", action="store_true",
                    help="start no session now: the loop starts each one when mail comes for it")
    sp.add_argument("--if-was-up", action="store_true",
                    help="only if the team was up (not taken down): the plugin's autostart after a restart")
    sp = p("run"); sp.add_argument("--once", action="store_true")
    sp = p("say")
    for x in ("channel", "sender", "type", "to"):
        sp.add_argument(x)
    sp.add_argument("text", nargs="+")
    for name in ("watch", "await"):
        sp = p(name); sp.add_argument("name")
        if name == "await":
            sp.add_argument("feature", nargs="?", default=None)
        sp.add_argument("--now", action="store_true")
        sp.add_argument("--also", default=""); sp.add_argument("--timeout", default="")
    sp = p("launch"); sp.add_argument("targets", nargs="+"); sp.add_argument("--resume", action="store_true")
    sp.add_argument("--now", action="store_true")
    sp = p("sleep"); sp.add_argument("name"); sp.add_argument("--force", action="store_true")
    p("status")
    sp = p("tail"); sp.add_argument("--lines", type=int, default=15)
    sp = p("compact-now"); sp.add_argument("name"); sp.add_argument("transcript", nargs="?", default="")
    sp = p("nudge"); sp.add_argument("name"); sp.add_argument("text", nargs="*")
    sp = p("down"); sp.add_argument("--close", action="store_true")
    sp = p("halt"); sp.add_argument("--wait", type=int, default=180); sp.add_argument("--grace", type=int, default=60)
    sp.add_argument("--reason", default="")
    sp = p("unhalt"); sp.add_argument("targets", nargs="*")
    p("ensure-loop")
    sp = p("drop"); sp.add_argument("ids", nargs="+"); sp.add_argument("--note", default="")
    a = ap.parse_args(argv)
    m = Path(a.manifest)
    if not m.exists() and not m.suffix:      # a team's name (gears) for teams/gears.toml
        named = Path(__file__).resolve().parents[2] / "teams" / f"{a.manifest}.toml"
        if named.exists():
            a.manifest = str(named)
    team = Team(a.manifest)
    rt = Runtime(team, log=logger(team))
    if a.cmd == "nudge":     # v1's nudge: a NOTE that is delivered like any message
        a.channel, a.sender, a.type, a.to, a.text = "general", "codeteam", "NOTE", a.name, a.text or ["Carry on."]
        return cmd_say(team, rt, a)
    try:
        {"up": cmd_up, "run": cmd_run, "say": cmd_say, "watch": cmd_watch, "await": cmd_await,
         "launch": cmd_launch, "sleep": cmd_sleep, "status": cmd_status, "compact-now": cmd_compact_now, "tail": cmd_tail,
         "down": cmd_down, "ensure-loop": cmd_ensure_loop, "drop": cmd_drop,
         "halt": cmd_halt, "unhalt": cmd_unhalt}[a.cmd](team, rt, a)
    except HerdrError as e:
        sys.exit(f"herdr: {e}")


if __name__ == "__main__":
    main()
