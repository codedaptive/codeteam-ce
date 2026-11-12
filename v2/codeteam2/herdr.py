"""A thin client for herdr (https://herdr.dev), the runtime codeteam v2 runs sessions on.

Everything goes through herdr's CLI, which prints one JSON object per command. Commands are
scoped to one herdr session (default "codeteam"), so codeteam's panes never mix with a
herdr the user runs for himself.
"""
import fcntl
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Compute the share path here: importing team executes bin/codeteam via load_v1().
if (share := str(Path(__file__).resolve().parents[2] / "share")) not in sys.path:
    sys.path.insert(0, share)
import codeteam_launchd

HERDR_BIN = os.environ.get("CODETEAM_HERDR_BIN") or shutil.which("herdr") or "/opt/homebrew/bin/herdr"
# Outside LaunchAgents so these plists are not automatically loaded at login.
LAUNCHD_DIR = Path.home() / ".local/state/codeteam2/launchd"
# launchd label prefix for the herdr server agents (CODETEAM_LAUNCHD_PREFIX, default com.codeteam).
LAUNCHD_PREFIX = os.environ.get("CODETEAM_LAUNCHD_PREFIX") or "com.codeteam"
# Display-only commands join reads here because they change no list a loop reads.
_NON_ACTIONS = frozenset({
    ("pane", "list"), ("agent", "list"), ("workspace", "list"), ("tab", "list"),
    ("pane", "read"), ("agent", "read"), ("agent", "get"),
    ("notification", "show"), ("pane", "report-metadata"),
})


def launchd_label(session: str) -> str:
    # Escaping underscores as well as other bytes keeps distinct session names distinct.
    return f"{LAUNCHD_PREFIX}.codeteam2.herdr." + "".join(
        chr(byte) if byte in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.-"
        else f"_{byte:02x}" for byte in session.encode("utf-8")
    )


class HerdrError(Exception):
    def __init__(self, code, message=""):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class Herdr:
    def __init__(self, session="codeteam", log=None):
        self.session = session
        self.log = log or (lambda *_: None)
        self.last_action = 0.0

    # ------------------------------------------------------------------ plumbing
    def _env(self):
        env = dict(os.environ, HERDR_SESSION=self.session)
        env.pop("HERDR_SOCKET_PATH", None)
        return env

    def run(self, *args, timeout=60, raw=False):
        """Run one herdr command. JSON commands return their `result`; raw ones their text."""
        try:
            r = subprocess.run([HERDR_BIN, *map(str, args)], capture_output=True, text=True,
                               env=self._env(), timeout=timeout)
        finally:
            if args[:1] != ("status",) and args[:2] not in _NON_ACTIONS:
                self.last_action = time.monotonic()
        if raw:
            if r.returncode:
                raise HerdrError("exit", (r.stderr or r.stdout).strip()[:500])
            return r.stdout
        text = (r.stdout.strip() or r.stderr.strip())
        data = None
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    data = json.loads(line)
                    break
                except ValueError:
                    continue
        if data is None:
            if r.returncode:
                raise HerdrError("exit", text[:500])
            return {}
        if data.get("error"):
            e = data["error"]
            raise HerdrError(e.get("code", "error"), e.get("message", ""))
        return data.get("result", data)

    # ------------------------------------------------------------------ server
    def server_running(self):
        r = subprocess.run([HERDR_BIN, "status", "server"], capture_output=True, text=True,
                           env=self._env(), timeout=15)
        return "status: running" in r.stdout

    def ensure_server(self, logfile: str | None = None) -> bool:
        if self.server_running():
            return False
        # Hold the directory at 0700: each plist holds the caller's environment (tokens included).
        LAUNCHD_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(LAUNCHD_DIR, 0o700)
        label = launchd_label(self.session)
        # Cron's ensure-loop and the loop must not boot out each other's starting server.
        # Keep the lock through the readiness poll; closing it releases it even on an error.
        with (LAUNCHD_DIR / f"{label}.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if self.server_running():
                return False
            domain = f"gui/{os.getuid()}"
            target = f"{domain}/{label}"
            job = subprocess.run(["launchctl", "print", target], capture_output=True, text=True, timeout=15)
            if not re.search(r"^\s*pid\s*=\s*\d+\s*$", job.stdout, re.MULTILINE):
                # A job without a pid can remain after exit; request bootout and wait before bootstrap.
                subprocess.run(["launchctl", "bootout", target], capture_output=True, text=True, timeout=15)
                if not codeteam_launchd.wait_for_bootout(target, timeout=15):
                    raise HerdrError("server_start", f"{target} still loaded 20 s after bootout; not bootstrapped")
                env = self._env()
                # The server may be started from cron (a bare PATH): give it Homebrew's and ~/.local/bin, where
                # claude lives, so herdr finds the agents' binaries for its own integration checks.
                env["PATH"] = f"/opt/homebrew/bin:{os.path.expanduser('~/.local/bin')}:" + env.get("PATH", "/usr/bin:/bin")
                # Start as a launchd job to avoid inheriting the caller's observed throttling.
                # RunAtLoad starts it at bootstrap: the plist lives outside LaunchAgents.
                # No KeepAlive: server stop stays a stop; cron's ensure-loop handles restarting.
                plist = LAUNCHD_DIR / f"{label}.plist"
                # The environment needs 0600; atomic publication keeps launchd from reading a partial plist.
                fd, temporary = tempfile.mkstemp(dir=LAUNCHD_DIR, prefix=label, suffix=".tmp")
                try:
                    with os.fdopen(fd, "wb") as stream:
                        # The caller's cwd may be deleted; Herdr has no team directory, so use home.
                        plistlib.dump({
                            "Label": label,
                            "ProgramArguments": [HERDR_BIN, "server", "--session", self.session],
                            "EnvironmentVariables": env,
                            "StandardInPath": "/dev/null",
                            "StandardOutPath": logfile or "/dev/null",
                            "StandardErrorPath": logfile or "/dev/null",
                            "WorkingDirectory": str(Path.home()),
                            "RunAtLoad": True,
                            # launchd's default class (no ProcessType, or Standard) runs a job and everything it
                            # starts at priority 20 with late timers; Interactive runs it like an app. Measured on
                            # this Mac, 2026-11-09: a 5 ms sleep took 18 ms under Standard and 6 ms under Interactive,
                            # and herdr's interface, unusable all afternoon, answered at once after the change.
                            "ProcessType": "Interactive",
                        }, stream)
                    os.replace(temporary, plist)
                finally:
                    Path(temporary).unlink(missing_ok=True)
                if (err := codeteam_launchd.bootstrap(domain, str(plist), timeout=15)) is not None:
                    raise HerdrError("server_start", err)
            for _ in range(50):
                time.sleep(0.2)
                if self.server_running():
                    return True
            raise HerdrError("server_start", f"herdr server --session {self.session} did not come up")

    # ------------------------------------------------------------------ layout
    def workspaces(self):
        return self.run("workspace", "list").get("workspaces", [])

    def workspace_create(self, cwd, label, env=None):
        args = ["workspace", "create", "--cwd", cwd, "--label", label, "--no-focus"]
        for k, v in (env or {}).items():
            args += ["--env", f"{k}={v}"]
        return self.run(*args)

    def tabs(self, workspace):
        return self.run("tab", "list", "--workspace", workspace).get("tabs", [])

    def tab_create(self, workspace, cwd, label):
        return self.run("tab", "create", "--workspace", workspace, "--cwd", cwd, "--label", label, "--no-focus")

    def tab_rename(self, tab, label):
        return self.run("tab", "rename", tab, label)

    def panes(self, workspace=None):
        args = ["pane", "list"] + (["--workspace", workspace] if workspace else [])
        return self.run(*args).get("panes", [])

    def pane_split(self, pane, direction, cwd):
        return self.run("pane", "split", pane, "--direction", direction, "--cwd", cwd, "--no-focus")

    def pane_rename(self, pane, label):
        return self.run("pane", "rename", pane, label)

    def pane_run(self, pane, command):
        return self.run("pane", "run", pane, command)

    def pane_read(self, pane, lines=40, source="recent-unwrapped"):
        return self.run("pane", "read", pane, "--source", source, "--lines", lines, raw=True)

    def pane_metadata(self, pane, source, display=None, tokens=None):
        """Display-only metadata in herdr's sidebar (never the agent's state)."""
        args = ["pane", "report-metadata", pane, "--source", source]
        if display:
            args += ["--display-agent", display]
        for k, v in (tokens or {}).items():
            args += ["--token", f"{k}={v}"] if v not in (None, "") else ["--clear-token", k]
        return self.run(*args)

    def pane_close(self, pane):
        return self.run("pane", "close", pane)

    def workspace_close(self, workspace):
        return self.run("workspace", "close", workspace)

    # ------------------------------------------------------------------ agents
    def agents(self):
        return self.run("agent", "list").get("agents", [])

    def agent_get(self, target: str) -> dict:
        return self.run("agent", "get", target).get("agent", {})

    def agent_rename(self, target, name):
        return self.run("agent", "rename", target, name)

    def agent_prompt(self, target, text, wait=False, timeout_ms=None):
        args = ["agent", "prompt", target, text]
        if wait:
            args.append("--wait")
        if timeout_ms:
            args += ["--timeout", timeout_ms]
        return self.run(*args, timeout=(timeout_ms / 1000 + 15) if timeout_ms else 60)

    def agent_send_keys(self, target, *keys):
        return self.run("agent", "send-keys", target, *keys)

    def agent_read(self, target, lines=60):
        return self.run("agent", "read", target, "--source", "recent-unwrapped", "--lines", lines, raw=True)

    def agent_screen(self, target, lines=40):
        """What is on the agent's screen now, with its colours (screen.draft reads the input box from it)."""
        return self.run("agent", "read", target, "--source", "visible", "--lines", lines, "--format", "ansi",
                        raw=True, timeout=20)

    def notify(self, title, body=""):
        try:
            return self.run("notification", "show", title, "--body", body, "--sound", "request")
        except HerdrError:
            return None
