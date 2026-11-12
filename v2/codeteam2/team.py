"""A team on codeteam v2: the manifest, the sessions, their role files and launch scripts.

v2 replaces codeteam's runtime (windows, launching, delivering messages, knowing who is
working or stuck) and keeps its process: the manifest format, the worktrees, the roles, the
zone guard and the git flow. So it loads codeteam v1 as a library for everything that is not
runtime, and points the runtime commands in every role file at codeteam2.
"""
from collections.abc import Iterator
from contextlib import contextmanager
import datetime as dt
import fcntl
import importlib.machinery
import importlib.util
import json
import os
import re
import shlex
import uuid
from dataclasses import dataclass
from pathlib import Path

V2_DIR = Path(__file__).resolve().parent.parent
CT_HOME = V2_DIR.parent
# Where team folders, bare repos and team links live (CODETEAM_WORKSPACE, default ~/codeteam-work).
WORKSPACE = Path(os.environ.get("CODETEAM_WORKSPACE") or Path.home() / "codeteam-work")
# The human who owns the teams, as a message sender and recipient (CODETEAM_OWNER, default Owner).
OWNER = os.environ.get("CODETEAM_OWNER") or "Owner"
CODETEAM2 = V2_DIR / "bin" / "codeteam2"

# The runtime verbs v2 owns. Everything else (unit, squash, push-up, integrate, promote,
# approve, retire, snapshot, drop, sweep, backup, ...) stays codeteam v1's.
RUNTIME_VERBS = {"say", "watch", "await", "launch", "sleep", "status", "nudge", "compact-now"}


START_FIELDS = ("sid", "starting_at", "awaiting_turn", "alerted", "wake_requested", "first_turn_seen",
                "last_mid", "last_mids", "startup_mids", "start_completion", "start_term")


def merge_starts(st: dict, disk: dict) -> list[str]:
    """Copy present START_FIELDS from newer disk starts and later disk wakes into st; return changed keys.

    A disk wake is copied only if later than both the snapshot's wake and its (possibly merged) start.
    """
    merged = []
    for key, saved in disk.items():
        if not isinstance(saved, dict) or not isinstance(st.get(key, {}), dict):
            continue
        rec = st.get(key, {})
        changed = False
        if (saved.get("starting_at") or 0) > (rec.get("starting_at") or 0):
            rec = st.setdefault(key, {})
            rec.update({field: saved[field] for field in START_FIELDS if field in saved})
            changed = True
        wake = saved.get("wake_requested") or 0
        if wake > max(rec.get("wake_requested") or 0, rec.get("starting_at") or 0):
            st.setdefault(key, {})["wake_requested"] = wake
            changed = True
        if changed:
            merged.append(key)
    return merged


def load_v1():
    p = CT_HOME / "bin" / "codeteam"
    loader = importlib.machinery.SourceFileLoader("codeteam_v1", str(p))
    spec = importlib.util.spec_from_loader("codeteam_v1", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


v1 = load_v1()


def agent_name(product, key):
    """herdr agent names: [a-z][a-z0-9_-]{0,31}, unique per herdr server. A key that already ends in the
    team's name is not named twice (gears-designer, not gears-designer-gears)."""
    if key.lower().endswith("-" + product.lower()) and len(key) > len(product) + 1:
        key = key[:-(len(product) + 1)]
    s = re.sub(r"[^a-z0-9_-]+", "-", f"{product}-{key}".lower()).strip("-")
    if not s or not s[0].isalpha():
        s = "t-" + s
    return s[:32].rstrip("-")



def default_warm_s(cache_ttl):
    """How long after its turn ends a session's prompt cache is still warm, with a margin: 55 min on
    the 1-hour cache (every codeteam-launched session since 2026-10-25, CTX1), 4 min on the 5-minute
    one. The spend analysis measured 85-97% of the prompt cached after 5+ min idle on the 1-hour cache."""
    return 3300 if str(cache_ttl) == "1h" else 240

@dataclass
class Session:
    key: str            # "orc", an assistant's name, or a lane's name
    display: str        # Orc-Smoke, Kong, Coord-alpha
    kind: str           # "staff" or "lane"
    agent: str          # herdr agent name, also the pane label
    cwd: Path


class Team:
    def __init__(self, manifest):
        self.manifest = str(Path(manifest).expanduser().resolve())
        self.t = v1.Team(self.manifest)
        t = self.t
        # Runtime commands in every role file point at codeteam2.
        orig_cmd = t.cmd
        t.cmd = lambda verb: (f"{CODETEAM2} {verb} {t.manifest}" if verb in RUNTIME_VERBS else orig_cmd(verb))
        self.cfg = dict(t.m.get("v2", {}))
        self.product = t.product
        self.home = t.home
        self.dir = t.home / "v2"
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "launch").mkdir(exist_ok=True)
        self.herdr_session = self.cfg.get("herdr_session", "codeteam")
        self.swap_idle_min = float(self.cfg.get("swap_idle_min", 20))
        self.blocked_alert_min = float(self.cfg.get("blocked_alert_min", 2))
        self.poll_s = float(self.cfg.get("poll_s", 2))
        # Seconds a message waits for others to join its prompt (bounded; 0 delivers at once).
        self.gather_s = float(self.cfg.get("gather_s", 30))
        # A session whose turn ended within warm_s is prompted at once (its prompt cache is warm).
        # By default this follows the cache lifetime the team's sessions are launched with.
        self.warm_s = float(self.cfg.get("warm_s", default_warm_s(t.m.get("session_cache_ttl", "1h"))))
        # A session idle this long with nothing waiting is ended, except those the user talks to
        # (keep_awake) and one whose pane shows a subagent's view or whose input box holds unsent text. v1's
        # tick did this at 6 h. 0: never.
        self.idle_exit_min = float(self.cfg.get("idle_exit_h", 6)) * 60
        # typing_guard: hold a session's mail while its input box holds unsent text. draft_alert_min: tell the owner,
        # once per episode, when unsent text or a subagent's view has held the session this long while real
        # (not ride-along) mail is queued for it.
        self.typing_guard = bool(self.cfg.get("typing_guard", True))
        self.draft_alert_min = float(self.cfg.get("draft_alert_min", 10))
        # v1's patrol checks, every patrol_min (0: off); findings ride along, never wake.
        self.patrol_min = float(self.cfg.get("patrol_min", 30))
        # Push the team's branches to GitHub this often (v1's backup rules; 0: off).
        self.backup_min = float(self.cfg.get("backup_min", 60))
        # Mail waiting when a session starts goes in its first prompt.
        self.mail_in_first_prompt = bool(self.cfg.get("mail_in_first_prompt", True))
        # Claude Code's unattended retry mode: waits out 429/529 and usage limits by itself.
        self.retry_watchdog = bool(self.cfg.get("retry_watchdog", True))

    # ------------------------------------------------------------------ sessions
    def team_json(self):
        return v1.load_team(self.t)

    def sessions(self):
        team = self.team_json()
        out = []
        for key in self.t.staff():
            cwd, display, *_ = v1.launch_target(self.t, team, key)
            out.append(Session(key, display, "staff", agent_name(self.product, key), Path(cwd)))
        for key in team["lanes"]:
            cwd, display, *_ = v1.launch_target(self.t, team, key)
            out.append(Session(key, display, "lane", agent_name(self.product, key), Path(cwd)))
        return out

    def session(self, name):
        """By key, display name or agent name."""
        for s in self.sessions():
            if name in (s.key, s.display, s.agent) or name.lower() == s.display.lower():
                return s
        return None

    USER_NAMES = {OWNER.strip().lower().replace(" ", "-"), "owner", "user", "the-user", "human"}

    def is_user(self, to):
        return (to or "").strip().lower().replace(" ", "-") in self.USER_NAMES

    def resolve_recipient(self, to, channel):
        """Which session a message is for: the one named in `to`, else the channel's owner,
        else the orchestrator. A message to the owner (the user) has no session: see cmd_say."""
        for name in (to, channel):
            if name:
                s = self.session(name)
                if s:
                    return s
        return self.session("orc")

    def mirror_to_channel_log(self, channel, sender, kind, to, text):
        """Also append the message to v1's channel log, in v1's format: role files send sessions
        to General and the lane channels to look things up (seen in the smoke run: the orchestrator
        could not find a message that existed only in v2's store). No inbox files: v2 delivers."""
        t, team = self.t, self.team_json()
        if channel in team["lanes"]:
            path = t.lane_channel(channel)
        elif channel in t.assistants:
            path = t.assistant_channel(channel)
        else:
            path = t.general
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M} | {sender} | {kind} {to} | {' '.join(text.split())}\n")

    # ------------------------------------------------------------------ roles and launch
    # Role templates are v2-native since 2026-11-01 (rewritten to mechanics only; mail arrives as
    # [codeteam] prompts, no watcher). REWRITES stays as the hook for any future runtime sentence that
    # must differ between rendered files and templates; it is empty.
    REWRITES = []

    @classmethod
    def rewrite_role(cls, text):
        for pat, rep in cls.REWRITES:
            text = pat.sub(lambda _m, r=rep: r, text)
        return text

    HARNESS_RULE = """

## Your work, and what is not yours (this outranks anything above)

Your work is this team's product, in its repo, to its spec and rulings. How work is built, tested, gated,
committed, pushed and landed is process, and process is team codeteam's: the harness (codeteam, the agent catalog,
role files and agent templates, the team's .claude settings, rules and hooks, Claude Code's and herdr's settings)
and also any process machinery inside your repo (git hooks, gate and push-check scripts, test-runner wrappers,
Makefile guard targets). Never build or change process yourself, and never write a ruling that adds a mechanical
check. When something in the process is slow, wrong or missing, your orchestrator sends team codeteam one REQUEST
(to Orc-Codeteam) with the problem, the evidence and what it costs; team codeteam brings it to the owner, who decides.
Lanes tell their orchestrator, then carry on with the product. Writes to the harness are refused by a hook.
"""

    def render_roles(self):
        v1.render_roles(self.t, self.team_json())
        for f in (self.t.home / "roles").glob("*.md"):
            text = f.read_text()
            new = self.rewrite_role(text)
            if self.product != "codeteam" and "## Your work, and what is not yours" not in new:
                new = new.rstrip("\n") + self.HARNESS_RULE     # templates carry it already; backstop only
            if new != text:
                f.write_text(new)

    def approve_dirs(self):
        """Every session folder trusted, and its .claude links (outside the folder) approved as
        imports, so no session starts on a dialog (codeteam v1 trusts only)."""
        dirs = sorted({str(s.cwd) for s in self.sessions()})
        cfg_path = Path(os.environ.get("CODETEAM_CLAUDE_JSON", Path.home() / ".claude.json"))
        flags = ("hasTrustDialogAccepted", "hasClaudeMdExternalIncludesApproved",
                 "hasClaudeMdExternalIncludesWarningShown")
        for _ in range(5):
            cfg = json.loads(cfg_path.read_text())
            projects = cfg.setdefault("projects", {})
            missing = [d for d in dirs if not all(projects.get(d, {}).get(f) for f in flags)]
            if not missing:
                return len(dirs)
            for d in missing:
                e = projects.setdefault(d, {})
                for f in flags:
                    e[f] = True
            tmp = cfg_path.with_name(cfg_path.name + ".codeteam2.tmp")
            tmp.write_text(json.dumps(cfg, indent=2))
            tmp.replace(cfg_path)
        return len(dirs)

    def state_path(self):
        return self.dir / "state.json"

    def _read_state(self) -> dict:
        """Read state without locking; the caller must hold state_lock."""
        try:
            return json.loads(self.state_path().read_text())
        except (OSError, ValueError):
            return {}

    def load_state(self) -> dict:
        # Wait for an in-progress start's two writes so readers cannot save its intermediate record.
        with self.state_lock():
            return self._read_state()

    @contextmanager
    def state_lock(self) -> Iterator[None]:
        # Lock a separate, stable inode: replacing state.json must not replace the lock itself.
        with (self.dir / "state.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _write_state(self, st: dict) -> None:
        # Separate temp names keep processes from clobbering each other's staged writes.
        tmp = self.state_path().with_name(f"state.json.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(st, indent=1, sort_keys=True))
        tmp.replace(self.state_path())

    def save_state(self, st: dict) -> None:
        with self.state_lock():
            merge_starts(st, self._read_state())
            self._write_state(st)

    def update_state(self, key: str, fields: dict) -> None:
        with self.state_lock():
            st = self._read_state()
            st.setdefault(key, {}).update(fields)
            self._write_state(st)

    def session_env(self, key):
        """`[v2.session_env.<session>]`: environment for one session only, added after the team's [env]
        (2026-10-29: CLAUDE_AUTO_BACKGROUND_TASKS tried on one lane before the team). The session is named
        by its key or its display name; a value of "" removes a team variable for that session."""
        tab = self.cfg.get("session_env", {})
        s = self.session(key)
        names = {key} | ({s.display, s.agent} if s else set())
        out = {}
        for name, vals in tab.items():
            if name in names:
                out.update({k: str(v) for k, v in vals.items()})
        return out

    def keep_awake(self):
        """Sessions never ended for being idle: the orchestrator and any designer (the sessions the user
        talks to; v1 never typed into them), plus `[v2] keep_awake`."""
        out = {"orc"} | {n for n, a in self.t.assistants.items() if str(a.get("role", "")).lower() == "designer"}
        for name in self.cfg.get("keep_awake", []):
            s = self.session(name)
            if s:
                out.add(s.key)
        return out

    @property
    def cap(self):
        """Lanes awake at once: `[v2] cap`, else v1's own setting (team/max-awake-lanes, read each time so
        it can change while the loop runs, then the manifest's max_awake_lanes), else 16. a v1 cap
        may be set in that file."""
        if "cap" in self.cfg:
            return int(self.cfg["cap"])
        f = self.t.home / "max-awake-lanes"
        if f.exists():
            try:
                return int(f.read_text().split()[0])
            except (ValueError, IndexError):
                pass
        if self.t.m.get("max_awake_lanes"):
            return int(self.t.m["max_awake_lanes"])
        return int(os.environ.get("CT_LANE_CAP", 16))

    def halted(self):
        """The user's whole-team stop (v1's team/HALTED): on v2 the loop starts and types nothing,
        and `up` and `launch` start no session, while it exists."""
        return (self.t.home / "HALTED").exists()

    def held(self, key):
        """A session the user put on hold (v1's team/held/<name>, 2026-10-24): never started by the
        loop and never prompted; its mail waits."""
        return (self.t.home / "held" / key).exists()

    def launch_settings(self, key, display):
        """The --settings for a session: the same as v1's write_launch_script sets (a test checks the
        keys), so a team behaves the same on either runtime."""
        t = self.t
        settings = {"autoMemoryDirectory": str(t.ledger(key) / "memory" / "auto"),
                    "worktree": {"baseRef": "head"},
                    "statusLine": {"type": "command",
                                   "command": f"'{CT_HOME / 'bin' / 'codeteam-statusline'}' '{t.home / 'questions.md'}'"}}
        if t.compact_window_of(key):   # else Claude Code's default
            settings["autoCompactWindow"] = t.compact_window_of(key)
        # The 1-hour prompt cache for codeteam-launched (long-running) sessions; subagents keep 5 minutes.
        settings["promptCacheTtl"] = t.m.get("session_cache_ttl", "1h")
        # What auto mode's classifier needs to know about the team's workflow (v1, 2026-10-24).
        settings["autoMode"] = {"environment": ["$defaults"] + list(v1.AUTO_MODE_ENVIRONMENT)}
        if display in os.environ.get("CODETEAM_RC_OFF", "").split(","):
            settings["remoteControlAtStartup"] = False
        return settings

    def ctx_env(self, key, model):
        """CODETEAM_CTX_WINDOW (the zone guard's handoff point) and, for gpt-* sessions through a model proxy,
        the real context window (v1's gpt_context_tokens, 2026-10-25)."""
        t = self.t
        gpt_ctx = t.m.get("gpt_context_tokens")
        is_gpt = str(model or "").lower().startswith("gpt-")
        env = {}
        if gpt_ctx and is_gpt:
            env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = str(int(gpt_ctx))
        env["CODETEAM_CTX_WINDOW"] = str(v1.compaction_point(t, t.compact_window_of(key) or (
            int(gpt_ctx) if gpt_ctx and is_gpt else v1.default_ctx_window(model))))
        # The model and effort the session launched with, for the effort-mode hook (2026-10-31).
        env["CODETEAM_MODEL"] = str(model or "")
        env["CODETEAM_EFFORT"] = str(t.effort_of(key) or "")
        return env

    def write_launch_script(self, s: Session, resume_sid=None, mail=None):
        """The script a session's pane runs. Like v1's launch script, minus the PID registry and
        the inbox: v2 knows the session's state from herdr and delivers messages as prompts. `mail`
        (a [codeteam] prompt) goes at the end of the first prompt, so a session started for mail
        takes it in its first turn."""
        t, team = self.t, self.team_json()
        cwd, display, agent, role, mode, model = v1.launch_target(t, team, s.key)
        if s.kind == "lane" and self.cfg.get("lane_model"):
            model = self.cfg["lane_model"]
        if s.kind == "staff" and self.cfg.get("staff_model"):
            model = self.cfg["staff_model"]
        if "agent" in self.cfg and not self.cfg["agent"] and (s.kind == "lane" or s.key == "orc"):
            agent = ""          # assistants keep theirs (Kong, Nagatha): their agent is their job
        flags = []
        if agent:
            flags += ["--agent", agent]
        if model:
            flags += ["--model", model]
        if t.effort_of(s.key):
            flags += ["--effort", t.effort_of(s.key)]
        if mode:
            flags += ["--permission-mode", mode]
        if t.isolate:   # v1: project settings only, no MCP
            flags += ["--setting-sources", "project,local", "--strict-mcp-config"]
        flags += ["--settings", json.dumps(self.launch_settings(s.key, display))]
        if v1.MCP_FILE.exists() and self.cfg.get("mcp", True):
            flags += ["--mcp-config", str(v1.MCP_FILE)]
            # `[v2] mcp_extra`: more MCP servers for this team only (e.g. artificial-analysis is
            # team-codeteam's, not every session's). A path, or a list of paths; ~ is expanded.
            extra = self.cfg.get("mcp_extra") or []
            for x in ([extra] if isinstance(extra, str) else extra):
                flags += ["--mcp-config", os.path.expanduser(str(x))]
        flags += ["--add-dir", str(t.lane_dir(s.key) if s.kind == "lane" else t.root)]
        flags += ["--name", display, "--append-system-prompt-file", str(role)]
        handoff = t.ledger(s.key) / "reports" / "handoff.md"
        tail = f"\n\nMail waiting for you:\n{mail}" if mail else ""
        if resume_sid:
            sid = resume_sid
            flags += ["--resume", sid, "codeteam v2 restarted you. Carry on with the work in progress; "
                      "new messages arrive as prompts that begin with [codeteam]." + tail]
        else:
            sid = str(uuid.uuid4())
            first = (f"You are {display}, part of team {self.product}, running on codeteam v2 (herdr). Your role file "
                     "is appended to your system prompt. Messages from the team arrive only as prompts that begin "
                     "with [codeteam], delivered when your turn ends; you need no watcher, and `watch` only says "
                     "whether mail is waiting. You reply and report with the say command your role file names. ")
            if handoff.exists():
                first += f"Your handoff from before is {handoff}: read it first. "
            # With mail in the first prompt, a lane once went straight at the work and skipped its role's
            # procedure (a request lead): name the procedure first (factory smoke run, 2026-10-26).
            first += ("Mail is waiting below. Before you act on it, find in your role file how this kind of work is "
                      "done (for a zone: through a request lead in its own worktree, never edits in your own "
                      "checkout) and do it exactly that way. When it is done, or waiting on someone else, end your "
                      "turn." if mail else
                      "When the work is done, or waiting on someone else, end your turn.")
            flags += ["--session-id", sid, first + tail]
        env = {k: t.expand(v) for k, v in {**v1.SESSION_ENV_DEFAULTS, **t.env}.items()}
        env.update({
            "TMPDIR": f"{t.scratchpad(s.key)}/", "CLAUDE_CODE_TMPDIR": str(t.scratchpad(s.key)),
            "GIT_AUTHOR_NAME": display, "GIT_COMMITTER_NAME": display,
            "CODETEAM_SESSION": s.key, "CODETEAM_HOME": str(CT_HOME), "CODETEAM_MANIFEST": t.manifest,
            **self.ctx_env(s.key, model),
            # v2: hooks that call codeteam (say, compact-now) reach codeteam2 instead.
            "CODETEAM_RUNTIME": "herdr", "CODETEAM_BIN": str(CODETEAM2),
            # herdr: the launcher execs claude, but say which agent this is anyway.
            "HERDR_AGENT": "claude",
        })
        for k, v in self.session_env(s.key).items():
            if v == "":
                env.pop(k, None)
            else:
                env[k] = t.expand(v)
        if self.retry_watchdog:
            # Claude Code's unattended retry mode waits out 429/529 errors and usage limits itself
            # (v1 typed a resume line after a backoff instead).
            env["CLAUDE_CODE_RETRY_WATCHDOG"] = "1"
        if s.kind == "lane":
            r = team["lanes"][s.key]
            env["CODETEAM_ZONE"] = r.get("path", "")
            if r.get("test"):
                env["ZONE_TEST"] = r["test"]
            if r.get("owns"):
                env["CODETEAM_OWNS"] = ":".join(r["owns"])
            env["CODETEAM_SWT"] = str(v1.lane_wt(t, s.key, r))
            if not t.lab:
                env["CODETEAM_EXCHANGE"] = str(t.ex_wt())
            env["MAKEFILES"] = str(CT_HOME / "zone" / "zone.mk")
        lines = ["#!/bin/bash -l", f"# codeteam v2 launch script for {display} (written by codeteam2; do not edit)",
                 f"cd {shlex.quote(str(cwd))} || {{ echo 'missing {cwd}'; exit 1; }}",
                 "[ \"$(cat .claude/.gitignore 2>/dev/null)\" = '*' ] && rm -f .claude/settings.local.json",
                 f"mkdir -p {shlex.quote(str(t.scratchpad(s.key)))} {shlex.quote(str(t.ledger(s.key) / 'memory' / 'auto'))}"]
        lines += [f"export {k}={shlex.quote(str(v))}" for k, v in env.items()]
        # The Mac's own ssh agent, not herdr's forward of an attached terminal's, which dies when no terminal is
        # attached; and git over ssh never waits at a prompt (2026-11-04: loops and pushes hung at a passphrase).
        lines += ['case "${SSH_AUTH_SOCK:-}" in *herdr*|"") s=$(launchctl getenv SSH_AUTH_SOCK 2>/dev/null); '
                  '[ -n "$s" ] && export SSH_AUTH_SOCK="$s";; esac',
                  "export GIT_SSH_COMMAND='/usr/bin/timeout 300 ssh -o ConnectTimeout=20 -o ServerAliveInterval=15 "
                  "-o ServerAliveCountMax=4 -o BatchMode=yes'"]
        # codeteam's bin first, as v1 does: its swift, cargo and xcodebuild go through codeteam-slot to the build
        # queue (a `dev` slot job; zone/docs/INTERFACE.md).
        lines += [f'export PATH="{CT_HOME}/bin:{V2_DIR}/bin:/opt/homebrew/bin:$HOME/.local/bin:$PATH"',
                  "exec " + " ".join(shlex.quote(x) for x in [v1.CLAUDE_BIN, *flags])]
        path = self.dir / "launch" / f"{s.key}.sh"
        path.write_text("\n".join(lines) + "\n")
        path.chmod(0o755)
        return path, sid
