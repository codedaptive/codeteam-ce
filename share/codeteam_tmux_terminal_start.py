"""tmux_terminal_start: when there is no tmux server, start one from Terminal for bin/codeteam's tmux_add (D505;
D524 moved it here from tmux_add, which had passed the coding rules' complexity limit).

macOS runs a process started from a background context (cron, an agent's shell) at a lower scheduling priority, and
every pane inherits the tmux server's. So with no server running, Terminal starts it, and the sessions get the same
priority as a Terminal window. CODETEAM_NO_TERMINAL (the test harness, tests/run.sh) skips Terminal. A loaded
machine can take well over 10 s to open the window and start tmux, so the caller passes a long wait (D505: 10 s
missed at load 54.6).
"""
import os
import shlex
import sys
import time
from collections.abc import Callable
from subprocess import CompletedProcess


def tmux_terminal_start(session: str, tab: str, cmd: str, *, tmux: Callable[..., CompletedProcess],
                        osa: Callable[[str], bool], warn: Callable[[str], None], tmux_bin: str, socket: str,
                        terminal_app: str, wait_s: float) -> CompletedProcess | None:
    """tmux's has-session result for `session` once Terminal has started the server with it. None when Terminal is
    not used: a server already runs, the platform is not macOS, or CODETEAM_NO_TERMINAL is set. Also None, after
    a warning, when Terminal cannot be scripted. In each None case the caller starts the server detached. Exits,
    naming the wait, when Terminal ran the start but `session` did not appear within wait_s."""
    if tmux("list-sessions").returncode == 0 or sys.platform != "darwin" or os.environ.get("CODETEAM_NO_TERMINAL"):
        return None
    args = " ".join(shlex.quote(x) for x in
                    [tmux_bin, "-L", socket, "new-session", "-d", "-s", session, "-n", tab, "-x", "220", "-y", "60", cmd])
    if not osa(f'tell application "{terminal_app}" to do script "{args.replace(chr(34), chr(92) + chr(34))}; exit"'):
        warn(f"Terminal could not be scripted to start tmux for {session}; starting it detached, "
             "at a background process's priority")
        return None
    for _ in range(int(wait_s / 0.25)):
        if tmux("has-session", "-t", f"={session}").returncode == 0:
            break
        time.sleep(0.25)
    r = tmux("has-session", "-t", f"={session}")
    if r.returncode:
        sys.exit(f"tmux could not start {tab} in {session}: Terminal ran the start, but no session "
                 f"{session} after {wait_s} s ({r.stderr.strip()})")
    return r
