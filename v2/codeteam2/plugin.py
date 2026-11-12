"""codeteam2 as a herdr plugin: a thin layer over the core.

herdr runs these through plugin/run.sh (see plugin/herdr-plugin.toml). Each one is an ordinary
codeteam2 command underneath; the plugin only works out which team it is about and where to show
it. The core (`codeteam2 <verb> <manifest>`) runs without the plugin, and the plugin adds:
- startup: when herdr's server starts, try `up --resume --if-was-up` for each team here whose
  entry in the plugin's teams.toml says autostart = true; print each outcome and try to append it
  to the startup log;
- a board, a message tail, a "say" prompt and the questions file, in herdr popups;
- wake and sleep for the session in the focused pane.

herdr plugins are global to the user and run for every herdr session, so team actions select only
teams using the current herdr session; startup also logs when there are no autostart teams here.

The plugin's config is HERDR_PLUGIN_CONFIG_DIR/teams.toml:

    [[team]]
    manifest = "~/codeteam-gamma-preview/teams/example.toml"
    autostart = true
"""
import json
import os
import re
import select
import subprocess
import sys
import time
import tomllib
from pathlib import Path

# The human who owns the teams, as a message sender (CODETEAM_OWNER, default Owner); as in team.py.
OWNER = os.environ.get("CODETEAM_OWNER") or "Owner"

V2_DIR = Path(__file__).resolve().parent.parent
CODETEAM2 = V2_DIR / "bin" / "codeteam2"
PLUGIN_ID = "codeteam.v2"
# A team's up starts staff one after another; a big team's took over 120 s.
# Fifteen minutes bounds a hung up; herdr puts no limit on a startup hook.
STARTUP_UP_TIMEOUT_S = 900
EXAMPLE_CONFIG = '''# Teams the codeteam herdr plugin manages (codeteam v2).
# autostart: on server start, try codeteam2 up --resume --if-was-up for this team.
#
# [[team]]
# manifest = "~/codeteam-gamma-preview/teams/example.toml"
# autostart = true
'''


# ---------------------------------------------------------------------- where we are
def herdr_bin():
    return os.environ.get("HERDR_BIN_PATH") or "/opt/homebrew/bin/herdr"


def herdr_session_name():
    """The herdr session this plugin command runs in, from its socket path (…/sessions/<name>/…)."""
    m = re.search(r"/sessions/([^/]+)/", os.environ.get("HERDR_SOCKET_PATH", ""))
    if m:
        return m.group(1)
    return os.environ.get("HERDR_SESSION") or "default"


def config_path():
    d = os.environ.get("HERDR_PLUGIN_CONFIG_DIR")
    return Path(d) / "teams.toml" if d else Path.home() / ".config" / "codeteam2" / "teams.toml"


def configured_teams():
    """[(manifest path, autostart)] from teams.toml; writes a commented example if there is none."""
    p = config_path()
    if not p.exists():
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(EXAMPLE_CONFIG)
        except OSError:
            pass
        return []
    data = tomllib.loads(p.read_text())
    return [(str(Path(t["manifest"]).expanduser().resolve()), bool(t.get("autostart", False)))
            for t in data.get("team", []) if t.get("manifest")]


def manifest_info(manifest):
    m = tomllib.loads(Path(manifest).read_text())
    return m.get("product", ""), m.get("v2", {}).get("herdr_session", "codeteam")


def teams_here():
    """The configured teams that use the herdr session this command runs in."""
    here = herdr_session_name()
    out = []
    for mf, auto in configured_teams():
        try:
            product, session = manifest_info(mf)
        except (OSError, ValueError):
            continue
        if session == here:
            out.append((mf, product, auto))
    return out


def context():
    try:
        return json.loads(os.environ.get("HERDR_PLUGIN_CONTEXT_JSON") or "{}")
    except ValueError:
        return {}


def find(d, key):
    """The first value for key anywhere in nested dicts and lists."""
    if isinstance(d, dict):
        if key in d and d[key] not in (None, ""):
            return d[key]
        for v in d.values():
            r = find(v, key)
            if r is not None:
                return r
    elif isinstance(d, list):
        for v in d:
            r = find(v, key)
            if r is not None:
                return r
    return None


def herdr_json(*args):
    r = subprocess.run([herdr_bin(), *args], capture_output=True, text=True, timeout=20)
    for line in reversed(r.stdout.strip().splitlines()):
        if line.startswith("{"):
            try:
                return json.loads(line).get("result", {})
            except ValueError:
                pass
    return {}


def focused_workspace_label():
    ctx = context()
    ws = ctx.get("workspace") if isinstance(ctx.get("workspace"), dict) else {}
    if ws.get("label"):
        return ws["label"]
    wid = ws.get("workspace_id") or os.environ.get("HERDR_WORKSPACE_ID") or find(ctx, "workspace_id")
    if wid:
        for w in herdr_json("workspace", "list").get("workspaces", []):
            if w.get("workspace_id") == wid:
                return w.get("label")
    return None


def focused_team():
    """The team of the focused workspace; the only team here if there is just one."""
    teams = teams_here()
    label = focused_workspace_label()
    for mf, product, _ in teams:
        if product == label:
            return mf
    return teams[0][0] if len(teams) == 1 else None


def focused_agent():
    """The herdr agent name (the pane label codeteam2 gives a session) of the focused pane."""
    ctx = context()
    p = ctx.get("pane") if isinstance(ctx.get("pane"), dict) else {}
    pane = p.get("pane_id") or os.environ.get("HERDR_PANE_ID") or find(ctx, "pane_id")
    label = p.get("label")
    if pane and not label:
        for p in herdr_json("pane", "list").get("panes", []):
            if p.get("pane_id") == pane:
                label = p.get("label")
    return label


def notify(title, body=""):
    subprocess.run([herdr_bin(), "notification", "show", title, "--body", body], capture_output=True, timeout=15)


def ct2(*args: str | Path, capture: bool = False, timeout: float = 120) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(CODETEAM2), *map(str, args)]
    if capture:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return subprocess.run(cmd)


# ---------------------------------------------------------------------- a key, for popups
def wait_key(timeout):
    """A key pressed within timeout seconds, or None. The terminal is put in cbreak mode by caller."""
    r, _, _ = select.select([sys.stdin], [], [], timeout)
    return sys.stdin.read(1) if r else None


def cbreak():
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    return lambda: termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _startup_line(log: Path, message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {' | '.join(message.splitlines())}"
    print(line, flush=True)
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------- entry points
def cmd_startup(_: object) -> int:
    """Try each local autostart team's up in order; print outcomes and return 1 if any failed."""
    teams = [(mf, product) for mf, product, auto in teams_here() if auto]
    state_dir = os.environ.get("HERDR_PLUGIN_STATE_DIR")
    log = Path(state_dir) / "startup.log" if state_dir else Path.home() / ".local/state/codeteam2/plugin-startup.log"
    _startup_line(log, f"herdr session {herdr_session_name()}: {len(teams)} autostart teams")
    failed = False
    for mf, product in teams:
        try:
            r = ct2("up", mf, "--resume", "--if-was-up", capture=True, timeout=STARTUP_UP_TIMEOUT_S)
        except Exception as exc:
            failed = True
            _startup_line(log, f"{product}: failed: {exc}")
            continue
        tail = (r.stdout or r.stderr).strip()[-400:]
        if r.returncode != 0:
            failed = True
            _startup_line(log, f"{product}: failed (exit {r.returncode}): {tail}")
        else:
            _startup_line(log, f"{product}: ok: {tail}")
    return int(failed)


def cmd_open(a):
    """An action that opens one of the plugin's popups."""
    if not teams_here():
        return
    subprocess.run([herdr_bin(), "plugin", "pane", "open", "--plugin", PLUGIN_ID, "--entrypoint", a.rest[0]])


def cmd_board(_):
    """Every team's sessions and mail, refreshed every 3 s. q or Esc closes."""
    teams = teams_here()
    restore = cbreak() if sys.stdin.isatty() else (lambda: None)
    try:
        while True:
            out = [f"codeteam board · herdr session {herdr_session_name()} · {time.strftime('%H:%M:%S')}   (q closes)\n"]
            if not teams:
                out.append(f"No teams for this herdr session. List them in {config_path()}.")
            for mf, product, _ in teams:
                r = ct2("status", mf, capture=True)
                out.append((r.stdout or r.stderr).rstrip() + "\n")
            sys.stdout.write("\x1b[H\x1b[2J" + "\n".join(out) + "\n")
            sys.stdout.flush()
            k = wait_key(3) if sys.stdin.isatty() else None
            if k in ("q", "Q", "\x1b"):
                return
            if not sys.stdin.isatty():
                return
    finally:
        restore()


def cmd_tail(_):
    mf = focused_team()
    if not mf:
        print("No codeteam team for this workspace.")
        time.sleep(3)
        return
    try:
        ct2("tail", mf, "--lines", "30")
    except KeyboardInterrupt:
        pass


def cmd_say(_):
    """Send the team a message from the owner: who to, what kind, what."""
    mf = focused_team()
    if not mf:
        print("No codeteam team for this workspace.")
        time.sleep(3)
        return
    sys.path.insert(0, str(V2_DIR))
    from codeteam2.team import Team
    team = Team(mf)
    names = [s.display for s in team.sessions()]
    print(f"Message to team {team.product}. Sessions: {', '.join(names)}")
    to = input("To (Enter: the orchestrator): ").strip() or team.t.orc_name()
    kind = (input("Type [REQUEST]: ").strip() or "REQUEST").upper()
    text = input("Message: ").strip()
    if not text:
        print("Nothing sent.")
        time.sleep(1.5)
        return
    ct2("say", mf, "general", OWNER, kind, to, text)
    input("Sent. Enter closes.")


def cmd_questions(_):
    mf = focused_team()
    if not mf:
        print("No codeteam team for this workspace.")
        time.sleep(3)
        return
    sys.path.insert(0, str(V2_DIR))
    from codeteam2.team import Team
    q = Team(mf).t.home / "questions.md"
    if not q.exists():
        print(f"No open questions ({q} does not exist).")
        input("Enter closes.")
        return
    subprocess.run(["less", "-R", str(q)])


def _session_cmd(verb, a):
    mf, agent = focused_team(), focused_agent()
    if not mf or not agent:
        notify("codeteam", f"{verb}: focus a codeteam session's pane first")
        return
    r = ct2(verb, mf, agent, capture=True)
    notify(f"codeteam {verb}", ((r.stdout or r.stderr).strip() or "done")[-300:])


def cmd_wake(a):
    _session_cmd("launch", a)


def cmd_sleep(a):
    _session_cmd("sleep", a)


COMMANDS = {"startup": cmd_startup, "open": cmd_open, "board": cmd_board, "tail": cmd_tail, "say": cmd_say,
            "questions": cmd_questions, "wake": cmd_wake, "sleep": cmd_sleep}


def main(argv: list[str]) -> int | None:
    import argparse
    ap = argparse.ArgumentParser(prog="codeteam2 plugin", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=sorted(COMMANDS))
    ap.add_argument("rest", nargs="*")
    a = ap.parse_args(argv)
    return COMMANDS[a.cmd](a)
