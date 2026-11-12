#!/usr/bin/env python3
"""codeteam v2: recovery and rollback on a smoke team kept running (`run.py --keep`), in its own
herdr session so no real team is touched.

    python3 v2/smoke/restart_test.py --name <smoke team> [--timeout 600]

1. Loop death: the loop's pane gets Ctrl-C; `codeteam2 ensure-loop` (what v1's cron wake runs every
   minute) must bring it back.
2. Server restart (a reboot, as far as herdr is concerned): `herdr server stop` for the team's session;
   ensure-loop must start the server, the plugin's startup hook must bring the orchestrator back
   (the team is listed in the plugin's teams.toml with autostart for the test), and a message from Owner
   must get an answer.
3. Rollback: `codeteam2 down` must hand the team back to v1: the up marker gone, the down flag set,
   and v1's `wake --plan` no longer standing aside.
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
import tomllib
from pathlib import Path

V2 = Path(__file__).resolve().parent.parent
CT = V2.parent
C2 = str(V2 / "bin" / "codeteam2")
HERDR = "/opt/homebrew/bin/herdr"
PLUGIN_CFG = Path.home() / ".config" / "herdr" / "plugins" / "config" / "codeteam.v2" / "teams.toml"


def run(*a, env=None, check=False, timeout=180):
    r = subprocess.run([str(x) for x in a], capture_output=True, text=True, env=env, timeout=timeout)
    if check and r.returncode:
        raise SystemExit(f"failed: {' '.join(map(str, a))}\n{r.stdout}{r.stderr}")
    return r


def say(msg):
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def wait(what, fn, timeout):
    say(f"waiting: {what} (up to {timeout}s)")
    t0 = time.time()
    while time.time() - t0 < timeout:
        if fn():
            return True, int(time.time() - t0)
        time.sleep(3)
    return False, int(time.time() - t0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--timeout", type=int, default=600)
    a = ap.parse_args()
    mpath = V2 / "teams" / f"{a.name}.toml"
    m = tomllib.loads(mpath.read_text())
    session = m.get("v2", {}).get("herdr_session", "codeteam")
    if session == "codeteam":
        raise SystemExit("run this on a smoke team in its own herdr session (run.py --herdr-session ...)")
    env = dict(os.environ, HERDR_SESSION=session)
    tdir = Path(m["worktree_root"]).expanduser() / "team" / "v2"
    db = tdir / "messages.db"
    sys.path.insert(0, str(V2))
    from codeteam2.team import Team
    from codeteam2.scheduler import Runtime
    team = Team(str(mpath))
    rt = Runtime(team, log=lambda *_: None)
    status = lambda: run(C2, "status", mpath).stdout
    checks = []

    panes = json.loads(run(HERDR, "pane", "list", env=env).stdout.strip().splitlines()[-1])["result"]["panes"]
    orc_pane = [p["pane_id"] for p in panes if p.get("label") == f"{team.product}-orc"][0]
    last_id = lambda: int(sqlite3.connect(str(db)).execute("SELECT COALESCE(MAX(id),0) FROM messages").fetchone()[0])

    say("step 0: typing guard")
    # 0. Someone is typing into the orchestrator: its mail waits until the input box is empty.
    draft = "half a thought for the orchestrator"
    run(HERDR, "pane", "send-text", orc_pane, draft, env=env)
    time.sleep(2)
    mid_mark = last_id()
    run(C2, "say", mpath, "general", "Owner", "NOTE", f"Orc-{a.name.capitalize()}",
        "Typing-guard check: when this reaches you, reply to Owner with one line saying you got it. Nothing else.")
    time.sleep(team.gather_s + 15)
    state = sqlite3.connect(str(db)).execute("SELECT state FROM messages WHERE id > ? AND target='orc'",
                                             (mid_mark,)).fetchone()
    held_ok = state is not None and state[0] == "queued" and "TYPING" in status()
    run(HERDR, "pane", "send-keys", orc_pane, *(["backspace"] * len(draft)), env=env)
    got, secs = wait("delivered once the box is empty", lambda: sqlite3.connect(str(db)).execute(
        "SELECT 1 FROM messages WHERE id > ? AND target='user' AND sender LIKE 'Orc-%'", (mid_mark,)).fetchone(), a.timeout)
    checks.append(("typing guard: held while text sits in the input box, delivered once it is cleared",
                   held_ok and bool(got), f"held={held_ok}, answered after {secs}s"))

    say("step 1: the loop dies")
    # 1. The loop dies.
    daemon = [p["pane_id"] for p in panes if p.get("label") == f"{team.product}-codeteam2"]
    run(HERDR, "pane", "send-keys", daemon[0], "ctrl+c", env=env)
    ok, _ = wait("loop down", lambda: not rt.loop_alive(), 30)
    run(C2, "ensure-loop", mpath)
    ok2, secs = wait("loop back", rt.loop_alive, 60)
    checks.append(("ensure-loop restarts a dead loop", ok and ok2, f"{secs}s"))

    say("step 2: herdr's server stops")
    # 2. The server stops (a reboot, for herdr); cron's ensure-loop and the plugin bring it back.
    cfg_before = PLUGIN_CFG.read_text() if PLUGIN_CFG.exists() else None
    PLUGIN_CFG.parent.mkdir(parents=True, exist_ok=True)
    PLUGIN_CFG.write_text((cfg_before or "") + f'\n[[team]]\nmanifest = "{mpath}"\nautostart = true   # restart_test\n')
    try:
        run(HERDR, "server", "stop", env=env)
        down, _ = wait("server down", lambda: "status: running" not in run(HERDR, "status", "server", env=env).stdout, 30)
        run(C2, "ensure-loop", mpath)
        up, secs = wait("server, loop and orchestrator back",
                        lambda: "loop alive" in status() and any(
                            ln.split()[1] in ("idle", "done", "working") for ln in status().splitlines()
                            if ln.strip().startswith(f"Orc-")), a.timeout)
        checks.append(("after a server stop: server, loop and orchestrator back (ensure-loop + plugin autostart)",
                       down and up, f"{secs}s"))
        mark = int(sqlite3.connect(str(db)).execute("SELECT COALESCE(MAX(id),0) FROM messages").fetchone()[0])
        run(C2, "say", mpath, "general", "Owner", "REQUEST", f"Orc-{a.name.capitalize()}",
            "Restart check: reply to Owner with one line saying you are back. Nothing else.")
        got, secs = wait("an answer", lambda: sqlite3.connect(str(db)).execute(
            "SELECT 1 FROM messages WHERE id > ? AND target='user' AND sender LIKE 'Orc-%'", (mark,)).fetchone(), a.timeout)
        checks.append(("a message after the restart gets an answer", bool(got), f"{secs}s"))
    finally:
        if cfg_before is None:
            PLUGIN_CFG.unlink(missing_ok=True)
        else:
            PLUGIN_CFG.write_text(cfg_before)

    say("step 3: rollback to v1")
    # 3. Rollback to v1.
    run(C2, "down", mpath)
    plan = run(CT / "bin" / "codeteam", "wake", mpath, "--plan").stdout
    rolled = not (tdir / "up").exists() and (tdir / "down").exists()
    checks.append(("down hands the team back to v1 (markers; v1 wake --plan no longer stands aside)",
                   rolled, plan.strip().splitlines()[-1][:120] if plan.strip() else "(v1 wake --plan: nothing to do)"))

    print(f"\ncodeteam v2 restart test '{a.name}' (herdr session {session})")
    for what, ok, ev in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {what}: {ev}")
    ok = all(c[1] for c in checks)
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
