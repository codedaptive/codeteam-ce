"""The deck's sources: every file, table and process list the dashboard shows, read into one snapshot dict.

The deck only reads. Nothing here takes, tests or releases a flock (the build queue runner's lock included) or runs
lsof or any git command (it runs `ps`, herdr's list commands and DiskScanner's `du`). The build queue is read from
its job files, queue.toml and queue-runner.json. The one thing written is DiskScanner's per-team cache
`<team home>/v2/deck/disk.json` (via a .tmp file, creating only the `deck` folder). Every reader returns None, an
empty value or "?" when its source fails, so one broken source never stops a refresh. The snapshot is plain JSON
(str paths, epoch floats, ints, bools, None).
"""
import contextlib
import datetime as dt
import json
import math
import os
import re
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
import tomllib
from bisect import bisect_left, bisect_right, insort
from concurrent.futures import ThreadPoolExecutor
from itertools import islice
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

from ..herdr import Herdr
from ..scheduler import _record_state
from ..store import RUNTIME
from ..team import CT_HOME, WORKSPACE, Team, v1
from . import model

# How much of a log or transcript a first read takes from the end: transcripts grow to many MB, so the deck
# limits initial reads to 64 KB, enough for its latest records.
TAIL = 65536
# The build queue's classes in the order the panel lists them, and the states a job file can be in.
QUEUE_CLASSES = ("full", "post", "pre", "dev")
JOB_STATES = ("queued", "running", "done", "broken")
# The fields copied from a job file into the snapshot. A whitelist: `env` (it can hold secrets) and `command` are
# never copied, and a field the runner adds later reaches the screen only once it is listed here.
JOB_FIELDS = ("ticket", "class", "key", "worktree", "team", "session", "submitted", "started", "finished", "pid",
              "state", "cost", "estimated_start", "kind", "position", "hold")
JOB_NUMBERS = ("submitted", "started", "finished", "cost", "estimated_start")
JOB_INTS = ("pid", "position")
JOB_TEXTS = ("kind", "hold")
# Why a queued job is held back: its warm is running, or the load or swap guard is on.
HOLDS = ("warm", "load", "swap")
# Each class's (guaranteed, ceiling) when queue.toml says nothing: the defaults of zone/docs/INTERFACE.md
# "queue.toml", copied from SHARES in bin/codeteam-buildq. A ceiling of 0 means none.
CLASS_SHARES = {"full": (1, 1), "post": (1, 2), "pre": (1, 2), "dev": (1, 0)}
RETENTION_HOURS = 24
# The longest window of the per-class wait statistics and broken counts: the last day. queue.toml's
# retention_hours narrows it, since the runner removes finished jobs older than that.
WAIT_WINDOW_S = 86400
# The numbers and holds read from the runner's state file, each None unless the runner is live; and how old its
# beat may be before the runner counts as stale (the runner's own default of $CODETEAM_BUILDQ_STALE).
RUNNER_NUMBERS = ("budget", "used", "load", "load_max", "swap", "swap_max")
RUNNER_HOLDS = ("load_hold", "swap_hold")
RUNNER_STALE_S = 60
# The warm's own timeout (share/claude-hooks/worktree-create.py times it out at 840 s): a warm lock whose holder
# record is unreadable and older than this cannot still be held.
WARM_TIMEOUT_S = 840
# A session that exited stays listed as "recently ended" for an hour.
RECENT_END_S = 3600
# The herdr session codeteam teams run in unless their manifest says otherwise (herdr.Herdr's default); its
# pane and agent lists are fetched while the manifests load.
DEFAULT_HERDR_SESSION = "codeteam"
# The folders of a worktree whose size the disk scan reports (those in model.BUILD_PARTS count as build output).
DISK_PARTS = ("cargo-target", "target", ".build", "node_modules", ".codegraph", "scratchpad")


class _Kept(dict):
    """A Cache dict that notes the Cache's clock each time a key is read or written, so Cache.prune can drop the
    keys no refresh has used lately."""

    def __init__(self, cache):
        super().__init__()
        self.cache = cache
        self.used = {}

    def __getitem__(self, key):
        self.used[key] = self.cache.clock
        return super().__getitem__(key)

    def __setitem__(self, key, value):
        self.used[key] = self.cache.clock
        super().__setitem__(key, value)

    def __contains__(self, key):
        self.used[key] = self.cache.clock
        return super().__contains__(key)

    def get(self, key, default=None):
        self.used[key] = self.cache.clock
        return super().get(key, default)

    def setdefault(self, key, default=None):
        self.used[key] = self.cache.clock
        return super().setdefault(key, default)

    def prune(self, before):
        for key in [k for k, at in self.used.items() if at < before]:
            del self.used[key]
            self.pop(key, None)


class Cache:
    """What the deck keeps between refreshes so each refresh reads little: byte offsets and running totals of the
    logs it follows, incremental transcript and subagent tail windows, what a changed file last said, Team objects
    per manifest mtime, and each source's last run (Cache.every), which sets its cadence. A fresh Cache reads every
    source once. Tail windows hold complete-line records and state verdicts by byte offset, plus the read offset
    and tail bytes for unfinished lines and the append-only rewrite check."""

    def __init__(self):
        self.clock = 0.0            # the `now` of the refresh in progress: when a _Kept key was last used
        # follow is never pruned: its totals (compactions, every session's last status-line record) cover the
        # log since the deck first read it, and a rebuild reads only the last TAIL bytes, so a dropped entry
        # would come back as a smaller, partial count. It holds a few numbers per transcript and one record per
        # session id per status-line log.
        self.follow = {}            # (kind, path) -> offset of the next unread byte, "partial", the reader's totals
        self.transcripts = _Kept(self)       # path -> ((inode, mtime_ns, size), _transcript_info's dict, window)
        self.subagents = _Kept(self)         # agent jsonl -> ((inode, mtime_ns, size), last_state, tokens, window)
        self.metas = _Kept(self)             # agent meta.json path -> ((mtime_ns, size), parsed object)
        self.listings = _Kept(self)          # subagents folder -> (folder mtime_ns, its agent-*.meta.json names)
        self.teams = _Kept(self)             # manifest path -> {"mtime", "v1", "t2", "sessions"}
        self.mail = _Kept(self)              # messages.db path -> (db/wal/minute key, value, window/waiting row indexes)
        self.states = _Kept(self)            # state.json or disk.json path -> ((mtime_ns, size), read_state's value)
        self.runs = _Kept(self)              # source key -> (time of its last run, its value)
        self.transcript_paths = _Kept(self)  # session id -> its transcript path
        self.worktree_roots = _Kept(self)    # session folder -> its worktree root
        self.procs = None           # (the ps dict matched, the watched worktrees, worktree -> build pids)
        self.proc_matches = {}      # (pid, args) -> None (names no build tool) or {worktree: build_procs matches}

    def prune(self, now):
        """Drop every _Kept entry unused for RECENT_END_S: a session that ended within the hour is still listed,
        so its entries are used each refresh until then, and one older than that is read afresh if it is listed
        again. Every source's interval is far shorter than an hour, so a dropped run is one that would run again
        anyway. proc_matches is rebuilt from each ps run, so it holds only live processes."""
        for kept in vars(self).values():
            if isinstance(kept, _Kept):
                kept.prune(now - RECENT_END_S)

    def due(self, source, now, interval_s):
        """Whether interval_s seconds have passed since source last ran (or it never ran); True counts as a run."""
        last = self.runs.get(source)
        if last and now - last[0] < interval_s:
            return False
        self.runs[source] = (now, None)
        return True

    def every(self, source, now, interval_s, fn):
        """fn()'s value, recomputed at most every interval_s seconds; a run that raises is not recorded."""
        last = self.runs.get(source)
        if not last or now - last[0] >= interval_s:
            last = self.runs[source] = (now, fn())
        return last[1]


# ---------------------------------------------------------------------------------------------- small readers
def parse_etime(text):
    """Seconds in a ps etime: MM:SS, HH:MM:SS or D-HH:MM:SS."""
    days, _, clock = text.rpartition("-")
    seconds = 0
    for part in clock.split(":"):
        seconds = seconds * 60 + int(part)
    return int(days or 0) * 86400 + seconds


def read_ps(text):
    """pid -> {etime_s, args} from `ps -axo pid,etime,args`; the header and lines that do not parse are skipped."""
    out = {}
    for line in text.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 2 or not parts[0].isdigit():
            continue
        try:
            out[int(parts[0])] = {"etime_s": parse_etime(parts[1]), "args": parts[2] if len(parts) > 2 else ""}
        except ValueError:
            continue
    return out


# The tools whose processes count as a build: the list of bin/watch-agent's build_running. A transcript can be
# silent for many minutes while one of them works.
BUILD_TOOLS = ("swift-frontend", "swift-build", "swiftc", "cargo", "rustc", "make", "xctest", "swift-test")


def build_procs(ps, worktree):
    """The processes whose args hold the worktree path as a whole path (not a prefix of a longer name /a/wt2, not
    the tail of a longer path /x/a/wt) and hold the name of one of BUILD_TOOLS anywhere in their args (as
    bin/watch-agent does): a `tail -f` of a log in the worktree is not a build."""
    path = str(worktree)
    found = re.compile(r"(?<![\w./-])" + re.escape(path) + r"(?=[/\s]|$)")
    # A plain substring test first: with hundreds of processes and dozens of worktrees the regex runs only on
    # the few args that hold the path at all.
    return [{"pid": pid, **p} for pid, p in ps.items() if path in p["args"] and found.search(p["args"])
            and any(t in p["args"] for t in BUILD_TOOLS)]


def _parse_lines(chunk):
    out = []
    for line in chunk.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _read_new(state, path, nbytes=TAIL):
    """The complete JSON records appended to path since the last call with this state. The first call (or the
    first after the file shrank) reads the last nbytes, drops the line the window cut, and records in
    state["partial"] whether it began mid-file. An unfinished last line waits for the next call. Raises OSError."""
    size = os.path.getsize(path)
    first = "offset" not in state or size < state["offset"]
    if not first and size == state["offset"]:
        return []
    if first:
        state.clear()
        start = max(0, size - nbytes)
    else:
        start = state["offset"]
    back = 1 if first and start else 0      # the byte before the window says whether its first line is whole
    with open(path, "rb") as f:
        f.seek(start - back)
        data = f.read()
    base = start - back
    if back:
        newline = data.find(b"\n")
        cut = len(data) if newline < 0 else newline + 1
        data, base = data[cut:], base + cut
    end = data.rfind(b"\n") + 1
    state["offset"] = base + end
    if first:
        state["partial"] = start > 0
    return _parse_lines(data[:end])


def tail_records(path, nbytes=TAIL):
    """The JSON records in the last nbytes of a file, first partial line dropped, bad lines skipped; [] if unreadable."""
    try:
        return _read_new({}, path, nbytes)
    except OSError:
        return []


def read_state(path):
    """A JSON object file (state.json, disk.json), or None."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def team_flags(home, now):
    """The team's loop state from its marker files, and the age of its heartbeat (None when unreadable)."""
    home = Path(home)
    v2 = home / "v2"
    if (home / "HALTED").exists():
        state = "HALTED"
    elif (v2 / "up").exists() and not (v2 / "down").exists():
        state = "up"
    else:
        state = "down" if (v2 / "down").exists() else "?"
    try:
        beat = max(0, now - int((v2 / "heartbeat").read_text().strip()))
    except (OSError, ValueError):
        beat = None
    return {"state": state, "heartbeat_age_s": beat}


def transcript_path(rec, projects_dir, hint=None, subdirs=None):
    """The session's transcript: the file state.json records, then `hint` (the path its status-line record gives),
    each only when it is named <sid>.jsonl and exists; else the newest <projects_dir>/*/<sid>.jsonl, looked for in
    subdirs (the projects folder's subfolders, listed once by the caller) when given. The record is not written."""
    sid = rec.get("sid")
    if not sid:
        return None
    for recorded in (rec.get("transcript"), hint):
        if recorded and os.path.basename(recorded) == f"{sid}.jsonl" and os.path.exists(recorded):
            return recorded
    folders = project_dirs(projects_dir) if subdirs is None else subdirs
    hits = sorted((p for p in (d / f"{sid}.jsonl" for d in folders) if p.exists()), key=lambda p: p.stat().st_mtime)
    return str(hits[-1]) if hits else None


def project_dirs(projects_dir):
    """The entries of the projects folder, one folder per working directory ([] when it cannot be listed)."""
    try:
        return list(Path(projects_dir).iterdir())
    except OSError:
        return []


def git_dir(worktree):
    """A worktree's git folder, without running git: its .git folder, or the folder a .git file names."""
    dot = Path(worktree) / ".git"
    if dot.is_dir():
        return str(dot)
    try:
        line = dot.read_text().splitlines()[0]
    except (OSError, IndexError):
        return None
    if not line.startswith("gitdir:"):
        return None
    return str((Path(worktree) / line.split(":", 1)[1].strip()).resolve())


def _worktree_root(cache, cwd):
    """The first folder at or above cwd that holds a .git, else None."""
    if cwd not in cache.worktree_roots:
        p = Path(cwd)
        cache.worktree_roots[cwd] = next((str(d) for d in (p, *p.parents) if (d / ".git").exists()), None)
    return cache.worktree_roots[cwd]


def _under(path, root):
    return path is not None and (path == root or str(path).startswith(f"{root}/"))


def _origin_url(config):
    try:
        lines = Path(config).read_text().splitlines()
    except OSError:
        return None
    section = ""
    for line in map(str.strip, lines):
        if line.startswith("["):
            section = line
        elif section == '[remote "origin"]' and line.startswith("url") and "=" in line:
            return line.split("=", 1)[1].strip()
    return None


def _repo_name_from_config(repo):
    """v1's repo_name_of without `git remote get-url`: the origin url in the repo's config file, else the folder name."""
    common = Path(repo)
    dot = git_dir(repo)
    if dot:
        common = Path(dot)
        pointer = common / "commondir"
        if pointer.is_file():
            common = (common / pointer.read_text().strip()).resolve()
    url = _origin_url(common / "config")
    if url:
        return url.rstrip("/").split("/")[-1].split(":")[-1].removesuffix(".git")
    return common.parent.name if common.name == ".git" else common.name.removesuffix(".git")


@contextlib.contextmanager
def _no_git():
    """While a Team lists its sessions, v1 names repos from the config file: its own lookup runs git, and the
    deck runs no git command."""
    saved = v1.repo_name_of
    v1.repo_name_of = _repo_name_from_config
    try:
        yield
    finally:
        v1.repo_name_of = saved


def _free_gb(path):
    try:
        st = os.statvfs(path)
    except OSError:
        return None
    return round(st.f_bavail * st.f_frsize / 2 ** 30, 2)


def _epoch(text):
    try:
        return dt.datetime.fromisoformat(text).timestamp()
    except (TypeError, ValueError):
        return None


def _local_midnight(now):
    return dt.datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


# ---------------------------------------------------------------------------------------------- messages
def read_messages(db_path, now):
    """The messages.db summary, or None. A WAL database with no -wal file (no writer) opens immutable: a plain
    read-only open would create -shm and -wal files in the team's folder. With a -wal file it opens read-only,
    which sees the writer's recent commits. RUNTIME commands are not counted anywhere."""
    path = Path(db_path)
    if not path.exists():
        return None
    mode = "mode=ro" if Path(f"{path}-wal").exists() else "mode=ro&immutable=1"
    try:
        # The URI is built with urllib.parse: Path.as_uri imports urllib.request, which costs over half a second.
        db = sqlite3.connect(f"file:{quote(str(path.resolve()))}?{mode}", uri=True, timeout=1)
        try:
            return _summarise_messages(db, now)
        finally:
            db.close()
    except sqlite3.Error:
        return None


def _top5(counts):
    return [[name, n] for name, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]]


def _new_target():
    return {"waiting": 0, "held": 0, "delivered_today": 0, "oldest_waiting_ts": None,
            "broadcasts": 0, "oldest_mail_ts": None}


def _count_window(db, now, midnight):
    """Counts over the last day's messages: per hour, today's senders and recipients, broadcasts, deliveries."""
    # Rows from a margin before the window, by local ts text; the exact day and hour tests are made on epochs.
    since = dt.datetime.fromtimestamp(min(midnight, now - 86400) - 3 * 3600).strftime("%Y-%m-%dT%H:%M:%S")
    rows = db.execute("SELECT ts, sender, recipient, target, state, delivered_at FROM messages "
                      "WHERE kind != ? AND (ts >= ? OR delivered_at >= ?)", (RUNTIME, since, since))
    counts = {"hourly": [0] * 24, "senders": {}, "recipients": {}, "broadcasts": 0, "delivered": 0, "by_target": {}}
    for ts, sender, recipient, target, state, delivered_at in rows:
        t = _epoch(ts)
        if t is not None and now - t < 86400:
            counts["hourly"][23 - int(max(now - t, 0) // 3600)] += 1
        if t is not None and t >= midnight:
            counts["senders"][sender] = counts["senders"].get(sender, 0) + 1
            counts["recipients"][recipient] = counts["recipients"].get(recipient, 0) + 1
            counts["broadcasts"] += recipient.lower() == "all"
        if state == "delivered" and (_epoch(delivered_at or ts) or 0) >= midnight:
            counts["delivered"] += 1
            counts["by_target"].setdefault(target, _new_target())["delivered_today"] += 1
    return counts


def _count_waiting(db, by_target):
    """Count non-RUNTIME queued and held messages of any age in by_target and return totals including broadcasts.
    Broadcasts are RULINGs or messages to all (case-insensitive); oldest_mail_ts excludes them."""
    totals = {"queued": 0, "held": 0, "broadcasts_waiting": 0}
    for ts, target, state, kind, recipient in db.execute(
            "SELECT ts, target, state, kind, recipient FROM messages WHERE kind != ? "
            "AND state IN ('queued', 'held') ORDER BY id", (RUNTIME,)):
        entry = by_target.setdefault(target, _new_target())
        entry["waiting"] += 1
        entry["held"] += state == "held"
        entry["oldest_waiting_ts"] = entry["oldest_waiting_ts"] or ts
        broadcast = kind == "RULING" or recipient.lower() == "all"
        entry["broadcasts"] += broadcast
        totals["broadcasts_waiting"] += broadcast
        if not broadcast:
            entry["oldest_mail_ts"] = entry["oldest_mail_ts"] or ts
        totals[state] += 1
    return totals


def _summarise_messages(db, now, counts=None, waiting=None):
    if counts is None:
        counts = _count_window(db, now, _local_midnight(now))
        waiting = _count_waiting(db, counts["by_target"])
    # The newest 200 serve each session's "recent messages"; the snapshot's own list keeps the newest 10.
    recent = [{"id": i, "ts": ts, "sender": sender, "kind": kind, "recipient": recipient, "target": target,
               "text": " ".join(body.split())[:80]}
              for i, ts, sender, kind, recipient, target, body in db.execute(
                  "SELECT id, ts, sender, kind, recipient, target, substr(body, 1, 400) FROM messages "
                  "WHERE kind != ? ORDER BY id DESC LIMIT 200", (RUNTIME,))]
    return {"hourly": counts["hourly"], "last_hour": counts["hourly"][23], "top_senders": _top5(counts["senders"]),
            "top_recipients": _top5(counts["recipients"]), "broadcasts_today": counts["broadcasts"], **waiting,
            "delivered_today": counts["delivered"],
            "last": [{k: r[k] for k in ("id", "ts", "sender", "kind", "recipient", "target", "text")}
                     for r in recent[:10]],
            "recent": recent, "by_target": counts["by_target"],
            "max_id": db.execute("SELECT COALESCE(MAX(id), 0) FROM messages").fetchone()[0]}


def _mail_change(index, entry, adding):
    if entry is None:
        return
    if adding:
        insort(index, entry)
    else:
        del index[bisect_left(index, entry)]


def _mail_group_change(groups, order, key, mid, adding):
    ids = groups.setdefault(key, [])
    if ids:
        _mail_change(order, (ids[0], key), False)
    _mail_change(ids, mid, adding)
    if ids:
        _mail_change(order, (ids[0], key), True)
    else:
        del groups[key]


class _MailSummary:
    """Retain non-RUNTIME rows in the SQL text window or waiting, with shared sorted epoch/group entries.
    Sender, recipient, target and non-RUNTIME kind-only edits are not detected; Store does not make them.
    A change into or out of RUNTIME changes the fetched ids when the row otherwise qualifies."""

    def __init__(self, inode):
        self.inode = inode
        self.fetched = []
        self.rows = {}
        self.epochs, self.deliveries, self.texts = [], [], []
        self.senders, self.recipients, self.targets = {}, {}, {}
        self.all_recipients = []
        self.midnight = None
        self.delivered_order, self.waiting_order = [], []
        self.waiting, self.waiting_ids, self.mail_ids = {}, {}, {}
        self.waiting_totals = {"queued": 0, "held": 0, "broadcasts_waiting": 0}
        self.rulings = set()

    def _toggle(self, row, adding):
        detector, sender, recipient, target, stamp, delivery = row
        mid, ts, state, delivered_at = detector
        for index, entry in ((self.epochs, stamp), (self.deliveries, delivery),
                             (self.texts, (max(ts, delivered_at or ""), mid))):
            _mail_change(index, entry, adding)
        for groups, key, entry in ((self.senders, sender, stamp), (self.recipients, recipient, stamp)):
            if entry is None:
                continue
            index = groups.setdefault(key, [])
            _mail_change(index, entry, adding)
            if not index:
                del groups[key]
        if recipient.lower() == "all":
            _mail_change(self.all_recipients, stamp, adding)
        self._delivery_change(row, adding)
        if state in ("queued", "held"):
            self._waiting_change(mid, state, target, mid in self.rulings or recipient.lower() == "all", adding)
        if not adding:
            self.rulings.discard(mid)

    def _delivery_change(self, row, adding):
        detector, _, _, target, _, delivery = row
        if delivery is not None and delivery[0] >= self.midnight:
            _mail_group_change(self.targets, self.delivered_order, target, detector[0], adding)

    def _waiting_change(self, mid, state, target, broadcast, adding):
        if target not in self.waiting:
            self.waiting[target] = _new_target()
        entry = self.waiting[target]
        step = 1 if adding else -1
        entry["waiting"] += step
        entry["held"] += (state == "held") * step
        entry["broadcasts"] += broadcast * step
        self.waiting_totals[state] += step
        self.waiting_totals["broadcasts_waiting"] += broadcast * step
        _mail_group_change(self.waiting_ids, self.waiting_order, target, mid, adding)
        if not broadcast:
            ids = self.mail_ids.setdefault(target, [])
            _mail_change(ids, mid, adding)
            if not ids:
                del self.mail_ids[target]
        if not entry["waiting"]:
            del self.waiting[target]

    def _set_midnight(self, midnight):
        # Only a local-midnight change needs a delivery recount, including when the clock moves back.
        if self.midnight == midnight:
            return
        self.midnight = midnight
        self.targets, self.delivered_order = {}, []
        for row in self.rows.values():
            self._delivery_change(row, True)

    def update(self, db, since, midnight):
        self._set_midnight(midnight)
        fetched = db.execute(
            "SELECT id, ts, state, delivered_at FROM messages WHERE kind != ? "
            "AND (ts >= ? OR delivered_at >= ? OR state IN ('queued','held')) ORDER BY id",
            (RUNTIME, since, since)).fetchall()
        # Keep the canonical detector tuples: retaining the new equal fetch as well would double those rows.
        if fetched == self.fetched:
            return
        start = bisect_left(self.fetched, (fetched[0][0],)) if fetched else len(self.fetched)
        retained = len(self.fetched) - start
        if fetched[:retained] == self.fetched[start:]:
            for detector in self.fetched[:start]:
                self._toggle(self.rows.pop(detector[0]), False)
            changed = fetched[retained:]
            self.fetched = self.fetched[start:]
            for detector in changed:
                self.fetched.append(self._replace(db, detector))
            return
        ids = {r[0] for r in fetched}
        for mid in self.rows.keys() - ids:
            self._toggle(self.rows.pop(mid), False)
        for i, detector in enumerate(fetched):
            if self.rows.get(detector[0], (None,))[0] != detector:
                self._replace(db, detector)
            fetched[i] = self.rows[detector[0]][0]
        self.fetched = fetched

    def _replace(self, db, detector):
        mid, ts, state, delivered_at = detector
        if mid in self.rows:
            self._toggle(self.rows[mid], False)
        sender, kind, recipient, target = db.execute(
            "SELECT sender, kind, recipient, target FROM messages WHERE id = ?", (mid,)).fetchone()
        # Repeated labels share strings; equal send/delivery times share both text and epoch entries.
        detector = (mid, ts, sys.intern(state), ts if delivered_at == ts else delivered_at)
        epoch = _epoch(ts)
        stamp = (epoch, mid) if epoch is not None else None
        delivery = None
        if state == "delivered":
            delivered = (_epoch(delivered_at) if delivered_at else epoch) or 0
            delivery = stamp if delivered == epoch else (delivered, mid)
        row = (detector, sys.intern(sender), sys.intern(recipient), sys.intern(target), stamp, delivery)
        self.rows[mid] = row
        if state in ("queued", "held") and kind == "RULING":
            self.rulings.add(mid)
        self._toggle(row, True)
        return detector

    def _window_counts(self, now, midnight):
        hourly, previous = [], 0
        for hour in range(1, 25):
            # Strict epoch cutoffs put future rows in the newest bucket, just like max(now - t, 0).
            count = len(self.epochs) - bisect_right(self.epochs, (now - hour * 3600, math.inf))
            hourly.append(count - previous)
            previous = count
        return {"hourly": hourly[::-1],
                "senders": {k: len(v) - bisect_left(v, (midnight,)) for k, v in self.senders.items()},
                "recipients": {k: len(v) - bisect_left(v, (midnight,)) for k, v in self.recipients.items()},
                "broadcasts": len(self.all_recipients) - bisect_left(self.all_recipients, (midnight,)),
                "delivered": len(self.deliveries) - bisect_left(self.deliveries, (midnight,)),
                "by_target": {k: {**_new_target(), "delivered_today": len(self.targets[k])}
                              for _, k in self.delivered_order}}

    def _exclude_margin(self, counts, now, midnight, since):
        # Epoch tests alone can include rows outside the oracle's independent SQL text margin.
        # Only waiting rows can be below since in this fetch, so correct all groups in one waiting-bounded walk.
        for _, mid in self.texts[:bisect_left(self.texts, (since,))]:
            _, sender, recipient, target, stamp, delivery = self.rows[mid]
            if stamp is not None:
                t = stamp[0]
                if now - t < 86400:
                    counts["hourly"][23 - int(max(now - t, 0) // 3600)] -= 1
                if t >= midnight:
                    counts["senders"][sender] -= 1
                    counts["recipients"][recipient] -= 1
                    counts["broadcasts"] -= recipient.lower() == "all"
            if delivery is not None and delivery[0] >= midnight:
                counts["delivered"] -= 1
                counts["by_target"][target]["delivered_today"] -= 1

    def _oldest(self, ids):
        # The oracle's `oldest or ts` picks the first nonempty timestamp, or the last empty one.
        ts = None
        for mid in ids:
            ts = self.rows[mid][0][1]
            if ts:
                break
        return ts

    def _waiting_counts(self, by_target):
        # Emit delivered targets by first qualifying id, then waiting-only targets by first waiting id.
        # This matches the oracle's two passes when its unordered window query scans in id order; --json keeps it.
        for _, target in self.waiting_order:
            entry = dict(self.waiting[target])
            entry["oldest_waiting_ts"] = self._oldest(self.waiting_ids[target])
            entry["oldest_mail_ts"] = self._oldest(self.mail_ids.get(target, ()))
            if target in by_target:
                entry["delivered_today"] = by_target[target]["delivered_today"]
            by_target[target] = entry
        return dict(self.waiting_totals)

    def counts(self, now, midnight, since):
        counts = self._window_counts(now, midnight)
        self._exclude_margin(counts, now, midnight, since)
        for key in ("senders", "recipients"):
            counts[key] = {k: n for k, n in counts[key].items() if n}
        counts["by_target"] = {k: v for k, v in counts["by_target"].items() if v["delivered_today"]}
        return counts, self._waiting_counts(counts["by_target"])


def _incremental_messages(path, now, previous):
    if not path.exists():
        return None, None
    mode = "mode=ro" if Path(f"{path}-wal").exists() else "mode=ro&immutable=1"
    try:
        db = sqlite3.connect(f"file:{quote(str(path.resolve()))}?{mode}", uri=True, timeout=1)
        try:
            inode = path.stat().st_ino
            summary = previous if previous and previous.inode == inode else _MailSummary(inode)
            midnight = _local_midnight(now)
            since = dt.datetime.fromtimestamp(min(midnight, now - 86400) - 3 * 3600).strftime("%Y-%m-%dT%H:%M:%S")
            summary.update(db, since, midnight)
            return _summarise_messages(db, now, *summary.counts(now, midnight, since)), summary
        finally:
            db.close()
    except sqlite3.Error:
        return None, None


# ---------------------------------------------------------------------------------------------- metrics, transcripts
def _metrics_fields(rec):
    raw = rec.get("raw") or {}
    window, cost, cache = raw.get("context_window") or {}, raw.get("cost") or {}, raw.get("prompt_cache") or {}
    return {"used_pct": window.get("used_percentage"), "window": window.get("context_window_size"),
            "cost_usd": cost.get("total_cost_usd"), "cache_warm": cache.get("warm"),
            "cache_expires_at": cache.get("expires_at"), "hit_ratio": cache.get("hit_ratio"),
            "model": (raw.get("model") or {}).get("id"), "effort": (raw.get("effort") or {}).get("level"),
            "ts": _epoch(rec.get("ts")), "cwd": raw.get("cwd") or rec.get("cwd"),
            "transcript_path": raw.get("transcript_path")}


def _metrics_state(path, cache):
    """The status-line log followed to its end: the last record of every session id seen so far."""
    state = cache.follow.setdefault(("metrics", str(path)), {})
    for rec in _read_new(state, path):
        sid = rec.get("session_id") or (rec.get("raw") or {}).get("session_id")
        if sid:
            state.setdefault("last", {})[sid] = _metrics_fields(rec)
    return state


def read_metrics(path, sid, cache=None):
    """The last status-line record of session sid in the log, or None."""
    try:
        return _metrics_state(path, cache or Cache()).get("last", {}).get(sid)
    except OSError:
        return None


def seat_cost_today(path, now, cache=None, root=None):
    """Today's spend across the sessions in the log whose last record is today (and whose folder is under root),
    each counted at its last total_cost_usd. A lower bound when the log was first read from mid-file
    (cache.follow[("metrics", path)]["partial"]); a session's total includes any spend before midnight."""
    try:
        last = _metrics_state(path, cache or Cache()).get("last", {})
    except OSError:
        return None
    midnight = _local_midnight(now)
    return float(sum(m["cost_usd"] or 0 for m in last.values()
                     if m["ts"] is not None and m["ts"] >= midnight and (root is None or _under(m["cwd"], root))))


def count_compactions(path, cache=None):
    """(compact_boundary records seen, partial): the last 64 KB on the first read, then only new bytes."""
    state = (cache or Cache()).follow.setdefault(("compactions", str(path)), {})
    try:
        records = _read_new(state, path)
    except OSError:
        return 0, True
    state["count"] = state.get("count", 0) + sum(_compaction(r) for r in records)
    return state["count"], state["partial"]


def _compaction(rec):
    return rec.get("type") == "system" and rec.get("subtype") == "compact_boundary"


def _message(rec):
    message = rec.get("message")
    return message if isinstance(message, dict) else {}


def _blocks(rec):
    content = _message(rec).get("content")
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def recent_tools(records: list[dict], n: int = 5) -> list[dict]:
    """Tool calls in record/block order, with name and an input summary of up to 60 characters. Positive n stops a
    newest-first walk after n calls; n <= 0 walks all calls and applies the slice [-n:]."""
    walk = reversed if n > 0 else iter
    blocks = (block for rec in walk(records) if rec.get("type") == "assistant"
              for block in walk(_blocks(rec)) if block.get("type") == "tool_use")
    calls = []
    for block in islice(blocks, n) if n > 0 else blocks:
        given = block.get("input") or {}
        calls.append({"name": block.get("name"), "summary": next(
            (str(given[k])[:60] for k in ("command", "file_path", "description", "pattern") if given.get(k)), "")})
    return calls[::-1] if n > 0 else calls[-n:]


def _pread(fd, size, offset):
    """Read size bytes at offset, or through EOF; a short nonempty pread is not EOF."""
    chunks = []
    while size:
        chunk = os.pread(fd, size, offset)
        if not chunk:
            break
        chunks.append(chunk)
        offset += len(chunk)
        size -= len(chunk)
    return b"".join(chunks)


def _window_bytes(path, st, window):
    """(tail bytes including their preceding byte, reset): read appends with raw fd I/O unless rebuilding."""
    reset = (not window or window["inode"] != st.st_ino or st.st_size < window["offset"]
             or st.st_size - window["offset"] > TAIL)
    fd = os.open(path, os.O_RDONLY)
    try:
        if not reset:
            # Transcripts are append-only; checking up to 32 bytes is a cheap guard against rewrites near the
            # read offset, not arbitrary earlier edits. Keep one byte before TAIL to recognise a whole first line.
            check = window["data"][-32:]
            reset = _pread(fd, len(check), window["offset"] - len(check)) != check
            if not reset:
                return (window["data"] + _pread(fd, st.st_size - window["offset"], window["offset"]))[-(TAIL + 1):], False
        start = max(0, st.st_size - TAIL - 1)
        return _pread(fd, st.st_size - start, start), True
    finally:
        os.close(fd)


def _line_state(raw, records=()):
    """The newest scheduler verdict among decoded splitlines pieces, including unfinished or cut lines."""
    pieces = raw.decode("utf-8", "ignore").splitlines()
    # A normal UTF-8 object has already been parsed for the records window. BOMs and UTF-16/32 byte JSON do not
    # have the same meaning to json.loads after UTF-8 decoding; Unicode separators can split an object apart.
    if len(pieces) == 1 and records and pieces[0].lstrip().startswith("{") and "\x00" not in pieces[0]:
        return _record_state(records[0])
    for piece in reversed(pieces):
        try:
            rec = json.loads(piece)
        except ValueError:
            continue
        if isinstance(rec, dict):
            state = _record_state(rec)
            if state is not None:
                return state
    return None


def _window_lines(data, base, cutoff, window):
    """Keep whole lines and their flat records by slicing off expired prefixes, then parse newly completed lines."""
    # The byte before the window belongs only to the boundary check. A cut fragment can supply scheduler state,
    # but is never a whole record, even if part of it parses as an object.
    begin = (data.find(b"\n") + 1 or len(data)) if cutoff else 0
    end = data.rfind(b"\n") + 1
    lines, records = [], []
    if window:
        drop_lines = drop_records = 0
        for offset, parsed, _ in window["lines"]:
            if offset >= cutoff:
                break
            drop_lines += 1
            drop_records += len(parsed)
        lines = window["lines"][drop_lines:]
        records = window["records"][drop_records:]
    start = max(begin, window["next"] - base) if window else begin
    offset = base + start
    for raw in data[start:end].split(b"\n")[:-1]:
        parsed = _parse_lines(raw)
        lines.append((offset, parsed, _line_state(raw, parsed)))
        records.extend(parsed)
        offset += len(raw) + 1
    return begin, end, lines, records


def _tail_window(path, st, window=None):
    """Extend or rebuild a TAIL records/state window; an unreadable tail has no records and state '?'."""
    try:
        data, reset = _window_bytes(path, st, window)
    except OSError:
        return {"inode": None, "offset": st.st_size, "data": b"", "next": st.st_size,
                "lines": [], "records": [], "state": "?"}
    base = st.st_size - len(data)
    cutoff = max(0, st.st_size - TAIL)
    begin, end, lines, records = _window_lines(data, base, cutoff, None if reset else window)
    state = (_line_state(data[max(end, cutoff - base):])
             or next((state for _, _, state in reversed(lines) if state is not None), None)
             or _line_state(data[cutoff - base:min(begin, end)]) or "?")
    return {"inode": st.st_ino, "offset": st.st_size, "data": data, "next": base + end, "lines": lines,
            "records": records, "state": state}


def recent_trace(records, n=12):
    """The names of the last n tools the assistant records called, oldest first. The default 12 bounds the
    focus box's one-line trace while keeping recent activity visible."""
    return [call["name"] for call in recent_tools(records, n)]


def _starts_turn(rec):
    """Whether a record opens a turn: a user record with anything beside tool results (a prompt, or text sent along
    with them). Tool results alone are user records inside the turn whose tool calls they answer, and so are
    isMeta records: Claude Code writes one mid-turn when a skill loads, carrying the skill's text."""
    blocks = _blocks(rec)
    return (rec.get("type") == "user" and not rec.get("isMeta")
            and not (blocks and all(b.get("type") == "tool_result" for b in blocks)))


def _count_reply(turn, message, seen):
    """Adds an assistant message's output tokens to its turn and makes its context the turn's, once per message id:
    Claude Code writes each content block of a reply as a record of its own, each with the whole reply's usage."""
    usage = message.get("usage")
    if not usage or message.get("id") in seen:
        return
    seen.add(message.get("id"))
    turn["output"] += usage.get("output_tokens") or 0
    turn["context"] = sum(usage.get(k) or 0
                          for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))


def turn_stats(records):
    """The turns in the records, oldest first, each {"output": tokens, "context": tokens}, with a compaction as
    {"compacted": True} where it fell; the last 12 entries bound the focus sparkline to recent activity. A turn is
    listed from its first assistant record, so a
    prompt nothing answered (a compaction's summary, a local command) adds none, and the records before the first
    prompt are the turn the tail began inside, its earlier output unseen. Context is input + cache read + cache
    creation of the turn's last usage, 0 while it has none. Replies of model <synthetic> are passed over: Claude Code
    writes one on an API error with all-zero usage, which would read as an emptied context and a turn of no output,
    so a turn they alone answered is not listed."""
    entries, seen, turn = [], set(), None
    for rec in records:
        if _compaction(rec):
            entries.append({"compacted": True})
            turn = None
        elif _starts_turn(rec):
            turn = None
        elif rec.get("type") == "assistant" and _message(rec).get("model") != "<synthetic>":
            if turn is None:
                turn = {"output": 0, "context": 0}
                entries.append(turn)
            _count_reply(turn, _message(rec), seen)
    return entries[-12:]


def turns_left(turns, window):
    """About how many more turns fit in the context window: the room left over the mean context growth per turn
    across up to the last 5 turns since the last compaction, rounded down, at least 0. None with fewer than 2 such
    turns, a growth of 0 or less, or no window."""
    contexts = []       # newest first
    for t in reversed(turns):
        if "compacted" in t or len(contexts) == 5:
            break
        contexts.append(t["context"])
    if window is None or len(contexts) < 2 or contexts[0] <= contexts[-1]:
        return None
    # The mean growth is (newest - oldest) / steps; multiplying through keeps it in integers, so the floor is exact.
    return max(0, (window - contexts[0]) * (len(contexts) - 1) // (contexts[0] - contexts[-1]))


def _transcript_info(path, cache):
    """The turn state, last tool calls, tool trace, per-turn tokens (turn_stats) and last non-empty cwd from a
    transcript's incremental tail window."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    sig = (st.st_ino, st.st_mtime_ns, st.st_size)
    hit = cache.transcripts.get(path)
    if not hit or hit[0] != sig:
        window = _tail_window(path, st, hit[2] if hit else None)
        records = window["records"]
        info = {"state": window["state"], "mtime": st.st_mtime,
                "tools": recent_tools(records), "trace": recent_trace(records), "turns": turn_stats(records),
                "cwd": next((r["cwd"] for r in reversed(records)
                             if isinstance(r.get("cwd"), str) and r["cwd"]), None)}
        hit = cache.transcripts[path] = (sig, info, window)
    return hit[1]


def _find_transcript(ctx, rec, metrics):
    """The session's transcript: the path found on an earlier refresh while it exists, else transcript_path with
    the status-line record's path as its hint. Its last resort, a look in every projects folder (hundreds of
    stats, the folder listed once per collect() call), runs at most every 30 s per session id: a sid that
    neither state.json nor the status line places is usually one whose transcript is gone."""
    sid = rec.get("sid")
    if not sid:
        return None
    known = ctx.cache.transcript_paths.get(sid)
    if known and os.path.exists(known):
        return known
    hint = (metrics or {}).get("transcript_path")
    path = transcript_path(rec, ctx.projects, hint, [])
    if path is None and ctx.cache.due(("transcript scan", sid), ctx.now, 30):
        if ctx.project_dirs is None:
            ctx.project_dirs = project_dirs(ctx.projects)
        path = transcript_path(rec, ctx.projects, hint, ctx.project_dirs)
    if path:
        ctx.cache.transcript_paths[sid] = path
    return path


# ---------------------------------------------------------------------------------------------- subagents
def _agent_tail(jsonl, st, cache):
    """(last_state, tokens) from an unfinished agent's incremental transcript tail window."""
    sig = (st.st_ino, st.st_mtime_ns, st.st_size)
    hit = cache.subagents.get(str(jsonl))
    if not hit or hit[0] != sig:
        window = _tail_window(jsonl, st, hit[3] if hit else None)
        records = window["records"]
        turns = [r for r in records if r.get("type") in ("user", "assistant")]
        if not turns:
            state = "?"
        elif turns[-1]["type"] == "assistant" and not any(b.get("type") == "tool_use" for b in _blocks(turns[-1])):
            state = "ended"
        else:
            state = "in-turn"
        usage = next((_message(r)["usage"] for r in reversed(turns)
                      if r["type"] == "assistant" and _message(r).get("usage")), None)
        keys = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens")
        tokens = None if usage is None else sum(usage.get(k) or 0 for k in keys)
        hit = cache.subagents[str(jsonl)] = (sig, state, tokens, window)
    return hit[1], hit[2]


def _read_meta(path, cache):
    """A subagent's meta.json, parsed again only when its (mtime_ns, size) changed: the agent rewrites it in place
    when it finishes, which changes the file's stat but not always its folder's. Raises OSError and ValueError."""
    st = os.stat(path)
    sig = (st.st_mtime_ns, st.st_size)
    hit = cache.metas.get(path)
    if not hit or hit[0] != sig:
        with open(path, encoding="utf-8") as f:
            hit = cache.metas[path] = (sig, json.load(f))
    return hit[1]


def _subagent(folder, name, now, cache, max_age_s):
    # Plain str paths: this runs for every agent file of every session, and pathlib's objects cost more than the
    # stat itself.
    agent_id = name[len("agent-"):-len(".meta.json")]
    jsonl = os.path.join(folder, f"agent-{agent_id}.jsonl")
    try:
        st = os.stat(jsonl)
        # An agent past max_age_s is left out before its meta.json is looked at.
        if now - st.st_mtime > max_age_s:
            return None
        meta = _read_meta(os.path.join(folder, name), cache)
    except (OSError, ValueError):
        return None
    if not isinstance(meta, dict):
        return None
    finished = bool(meta.get("finished"))
    state, tokens = ("?", None) if finished else _agent_tail(jsonl, st, cache)
    return {"id": agent_id, "type": meta.get("agentType"), "description": meta.get("description"),
            "depth": meta.get("spawnDepth", 1), "parent": meta.get("parentAgentId"), "finished": finished,
            "worktree": meta.get("inheritedWorktreePath"), "started": getattr(st, "st_birthtime", st.st_ctime),
            "last_write": st.st_mtime, "last_state": state, "tokens": tokens}


def read_subagents(session_dir, now, cache=None, max_age_s=21600):
    """The session's subagents written within max_age_s: running ones, and finished ones (their write time is
    what the waiting-on-a-finished-child flag compares). Transcript tails are read for unfinished agents only."""
    cache = cache or Cache()
    folder = os.path.join(session_dir, "subagents")
    agents = (_subagent(folder, name, now, cache, max_age_s) for name in _meta_names(folder, cache))
    return [a for a in agents if a]


def _meta_names(folder, cache):
    """The folder's agent-*.meta.json names, sorted, from one scandir that is done again only when the folder's
    mtime_ns changed (a file added, removed or renamed); a file rewritten in place is _subagent's own stat's to
    see. [] when the folder cannot be read."""
    try:
        mtime = os.stat(folder).st_mtime_ns
        hit = cache.listings.get(folder)
        if not hit or hit[0] != mtime:
            with os.scandir(folder) as entries:
                names = sorted(e.name for e in entries if e.name.startswith("agent-") and e.name.endswith(".meta.json"))
            hit = cache.listings[folder] = (mtime, names)
    except OSError:
        return []
    return hit[1]


# ---------------------------------------------------------------------------------------------- locks
def read_holder(path, alive_pids):
    """The holder record of a warm lock. held: one JSON object with an int pid in alive_pids;
    free: it parses and that pid is gone; ?: empty, another shape (the old format), unreadable, or alive_pids
    unknown (None). The file is only read: never opened for writing, never flocked."""
    try:
        rec = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {"state": "?"}
    pid = rec.get("pid") if isinstance(rec, dict) else None
    if not isinstance(pid, int) or isinstance(pid, bool) or alive_pids is None:
        return {"state": "?"}
    if pid not in alive_pids:
        return {"state": "free"}
    return {"state": "held", **{k: rec.get(k) for k in ("pid", "team", "session", "worktree", "tool", "since")}}


def read_warm(worktree, alive_pids, now):
    """The worktree's warm in progress, or None: no lock, a dead holder, or an unreadable lock older than the
    warm's own timeout."""
    gd = git_dir(worktree)
    if not gd:
        return None
    lock = Path(gd) / "codeteam-warm.lock"
    try:
        age = now - lock.stat().st_mtime
    except OSError:
        return None
    holder = read_holder(lock, alive_pids)
    if holder["state"] == "held":
        return {**holder, "elapsed_s": now - (holder["since"] or now)}
    if holder["state"] == "?" and age <= WARM_TIMEOUT_S:
        return {"state": "?", "worktree": str(worktree)}
    return None


# ---------------------------------------------------------------------------------------------- build queue
def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _number(value):
    return value if _is_number(value) else None


def _finite(value):
    """Whether value is a number that is not nan or infinite. json.loads accepts both, and a whole number too big
    for a float is not finite for the arithmetic that follows."""
    try:
        return _is_number(value) and math.isfinite(float(value))
    except OverflowError:
        return False


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _text(value):
    return value if isinstance(value, str) else None


def _conf_num(value, default):
    """The runner's `num` (bin/codeteam-buildq): value as a finite float, else default. A numeric string reads as a
    number and true as 1.0, exactly as the runner reads queue.toml; a whole number too big for a float is the
    default too."""
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def read_job(path):
    """A job file of the build queue as a dict of JOB_FIELDS (a field the file lacks is None), or None when the file
    cannot be read or is not a job: not a JSON object, a state outside JOB_STATES or a class outside QUEUE_CLASSES.
    The ticket is the file's name when the file gives none. A time or cost that is not a number, a pid or position
    that is not an int and a kind or hold that is not text is None, so a row written oddly cannot fail a
    calculation later. The file is only read."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError, RecursionError):  # RecursionError: a file nested too deep for the parser
        return None
    if not isinstance(data, dict) or data.get("state") not in JOB_STATES or data.get("class") not in QUEUE_CLASSES:
        return None
    job = {k: data.get(k) for k in JOB_FIELDS}
    job.update({k: _number(job[k]) for k in JOB_NUMBERS})
    job.update({k: _int(job[k]) for k in JOB_INTS})
    job.update({k: _text(job[k]) for k in JOB_TEXTS})
    if not isinstance(job["ticket"], str):
        job["ticket"] = Path(path).name.removesuffix(".json")
    return job


def _table(data, name):
    """data[name] when it is a table, else {} (a value of the wrong type says nothing)."""
    table = data.get(name)
    return table if isinstance(table, dict) else {}


def read_queue_config(path):
    """What the deck uses of queue.toml, each key read as the runner's load_config reads it with the same defaults
    (a file that is missing, unreadable or not TOML, or a value of the wrong type, gives that key its default):
    retention_hours, and each class's guaranteed and ceiling counts from its [classes.<name>] table. The budget and
    the guards are not read here: they come from the runner's state (read_runner)."""
    try:
        data = tomllib.loads(Path(path).read_text())
    except (OSError, ValueError, RecursionError):  # RecursionError: a file nested too deep for the parser
        data = {}
    classes = _table(data, "classes")
    return {"retention_hours": _conf_num(data.get("retention_hours"), RETENTION_HOURS),
            "classes": {name: {"guaranteed": int(_conf_num(_table(classes, name).get("guaranteed"), guaranteed)),
                               "ceiling": int(_conf_num(_table(classes, name).get("ceiling"), ceiling))}
                        for name, (guaranteed, ceiling) in CLASS_SHARES.items()}}


def _runner(state, **fields):
    return {"state": state, "pid": None, "beat_age_s": None,
            **{k: None for k in RUNNER_NUMBERS + RUNNER_HOLDS}, **fields}


def read_runner(path, alive_pids, now):
    """The build queue runner as queue-runner.json shows it. state is "none" (no file), "?" (a file that cannot be
    read, is not a JSON object or has no numeric beat), "stale" (the beat is older than $CODETEAM_BUILDQ_STALE
    seconds, 60 by default, or its pid is not in alive_pids) or "live". Only a live runner gives its numbers
    (finite ones; a hold only when it is a bool): of any other, the deck shows nothing it cannot vouch for. Only
    reads: no lock of the runner's is taken or tested."""
    try:
        data = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return _runner("none")
    except (OSError, ValueError, RecursionError):
        return _runner("?")
    if not isinstance(data, dict) or not _finite(data.get("beat")):
        return _runner("?")
    pid, age = _int(data.get("pid")), now - data["beat"]
    gone = alive_pids is not None and pid is not None and pid not in alive_pids
    if age > _conf_num(os.environ.get("CODETEAM_BUILDQ_STALE"), RUNNER_STALE_S) or gone:
        return _runner("stale", pid=pid, beat_age_s=age)
    return _runner("live", pid=pid, beat_age_s=age,
                   **{k: data[k] if _finite(data.get(k)) else None for k in RUNNER_NUMBERS},
                   **{k: data[k] if isinstance(data.get(k), bool) else None for k in RUNNER_HOLDS})


def _queue_jobs(queue_dir):
    """(the readable jobs, the count of *.json files that are not jobs) in the queue folder; raises OSError when the
    folder cannot be listed. Only *.json names are read: a name starting with a dot or ending .tmp (the runner's
    temporary file before its rename), a lock and a log are skipped, not counted."""
    jobs, unknown = [], 0
    for f in sorted(Path(queue_dir).iterdir()):
        if f.suffix != ".json" or f.name.startswith("."):
            continue
        job = read_job(f)
        if job is None:
            unknown += 1
        else:
            jobs.append(job)
    return jobs, unknown


def _since(now, then):
    return None if then is None else now - then


def _running_order(job):
    """Running jobs oldest start first, those without a start last, the ticket breaking ties."""
    return (job["started"] is None, job["started"] or 0, job["ticket"])


def _waiting_order(job):
    """Queued jobs as the runner numbered them: by the position in the file, then oldest submit, then ticket; a job
    without either goes after those with it."""
    return (job["position"] is None, job["position"] or 0, job["submitted"] is None, job["submitted"] or 0,
            job["ticket"])


def _waits(jobs, now, window_s):
    """The wait statistics over jobs (of any state) that started inside the window."""
    waits = [max(j["started"] - j["submitted"], 0) for j in jobs
             if j["started"] is not None and j["submitted"] is not None and now - window_s <= j["started"] <= now]
    return {"n": len(waits), "median_s": statistics.median(waits) if waits else None, "max_s": max(waits, default=None),
            "window_h": window_s / 3600}


def _queue_class(cls, jobs, config, alive_pids, now):
    mine = [j for j in jobs if j["class"] == cls]
    running = [{**j, "running_s": _since(now, j["started"]),
                "pid_alive": None if alive_pids is None else j["pid"] in alive_pids}
               for j in sorted((j for j in mine if j["state"] == "running"), key=_running_order)]
    queued = [{**j, "waiting_s": _since(now, j["submitted"])}
              for j in sorted((j for j in mine if j["state"] == "queued"), key=_waiting_order)]
    # The runner removes finished jobs after retention_hours, so a retention shorter than a day leaves only that
    # much of the day to count.
    window_s = min(WAIT_WINDOW_S, config["retention_hours"] * 3600)
    broken = [j for j in mine if j["state"] == "broken" and j["finished"] is not None
              and now - window_s <= j["finished"] <= now]
    return {"class": cls, **config["classes"][cls], "held": {h: sum(q["hold"] == h for q in queued) for h in HOLDS},
            "running": running, "queued": queued, "waits": _waits(mine, now, window_s), "broken": len(broken)}


def read_queue(queue_dir, config_path, alive_pids, now):
    """The build queue for the snapshot: the runner's state (read_runner, from queue-runner.json beside the queue
    folder) and its classes, each with its guaranteed and ceiling counts, its running and queued jobs, how many
    queued jobs are held for each reason, wait statistics and broken count. state is "?" when queue_dir is not a
    folder that can be read. A running job whose pid is not in alive_pids is flagged (pid_alive), never acted on.
    Queued jobs are in the order of the position the runner wrote into each file. Only reads."""
    config = read_queue_config(config_path)
    try:
        jobs, unknown = _queue_jobs(queue_dir)
        state = "ok"
    except OSError:
        jobs, unknown, state = [], 0, "?"
    return {"state": state, "unknown": unknown,
            "runner": read_runner(Path(queue_dir).parent / "queue-runner.json", alive_pids, now),
            "classes": [_queue_class(cls, jobs, config, alive_pids, now) for cls in QUEUE_CLASSES]}


# ---------------------------------------------------------------------------------------------- disk
def parse_du(text, root):
    """`du -k -d N <root>` output -> the team's size and its five largest worktrees. A worktree is a folder under
    root holding a .git (file or folder); du walks into one too, and a folder nested in a listed one is left out here."""
    sizes = {}
    for line in text.splitlines():
        kb, _, path = line.partition("\t")
        if kb.isdigit():
            sizes[path] = int(kb)
    gb = lambda kb: round(kb / 2 ** 20, 2)
    worktrees = []
    for path in sorted(sizes):
        if path != str(root) and os.path.lexists(os.path.join(path, ".git")) \
                and not any(path.startswith(w["path"] + "/") for w in worktrees):
            parts = {p: gb(sizes[f"{path}/{p}"]) for p in DISK_PARTS if f"{path}/{p}" in sizes}
            worktrees.append({"path": path, "size_gb": gb(sizes[path]), "parts": parts})
    worktrees.sort(key=lambda w: -w["size_gb"])
    return {"size_gb": gb(sizes.get(str(root), 0)), "worktrees": worktrees[:5]}


class DiskScanner:
    """Sizes of the team folders, measured in a background thread, one team at a time, with `nice -n 19 du`.
    roots maps a team name to its root folder (change it between passes to follow the manifests); cache_dir_for(name)
    gives the folder for that team's disk.json (None: no file). A cache file is written only when the folder's
    parent (the team's v2 folder) exists, and only the `deck` folder is created. A pass skips a team whose
    disk.json is younger than interval_s unless a scan was asked for."""

    def __init__(self, roots, interval_s=600, cache_dir_for=lambda team: None):
        self.roots = dict(roots)
        self.interval_s = interval_s
        self.cache_dir_for = cache_dir_for
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._force = False
        self._thread = None
        self._result = {"at": None, "teams": {}}

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="deck-disk", daemon=True)
            self._thread.start()

    def scan_now(self):
        """Ask for a pass of every team now, starting the thread if it is not running."""
        self._force = True
        self._wake.set()
        self.start()

    def result(self):
        with self._lock:
            return {"at": self._result["at"], "teams": dict(self._result["teams"])}

    def _run(self):
        while True:
            self.scan_pass()
            self._wake.wait(self.interval_s)
            self._wake.clear()

    def scan_pass(self):
        """One measurement of every team (those whose disk.json is still fresh are skipped unless forced)."""
        force, self._force = self._force, False
        for team, root in list(self.roots.items()):
            cache_dir = self.cache_dir_for(team)
            if not force and cache_dir and self._fresh(cache_dir / "disk.json"):
                continue
            entry = self._measure(root)
            if entry is None:
                continue
            entry["at"] = time.time()
            with self._lock:
                self._result["teams"][team] = entry
                self._result["at"] = entry["at"]
            if cache_dir and cache_dir.parent.exists():
                cache_dir.mkdir(exist_ok=True)
                tmp = cache_dir / "disk.json.tmp"
                tmp.write_text(json.dumps(entry))
                tmp.replace(cache_dir / "disk.json")

    def _fresh(self, path):
        data = read_state(path)
        return bool(data) and time.time() - (data.get("at") or 0) < self.interval_s

    @staticmethod
    def _measure(root):
        try:
            # nice: a scan of a large tree must not compete with builds. -d 6 reaches the build folders of
            # worktrees nested a few folders under the root; the 30 min timeout bounds a tree that never finishes.
            done = subprocess.run(["nice", "-n", "19", "du", "-k", "-d", "6", str(root)], capture_output=True,
                                  text=True, timeout=1800)
        except (OSError, subprocess.SubprocessError):
            return None
        return parse_du(done.stdout, root) if done.stdout else None


# ---------------------------------------------------------------------------------------------- the snapshot
def _read_ps(text):
    """(read_ps of text, or of a `ps` run when text is None; the error when ps fails, else None)."""
    if text is None:
        try:
            text = subprocess.run(["ps", "-axo", "pid,etime,args"], capture_output=True, text=True, timeout=5,
                                  check=True).stdout
        except (OSError, subprocess.SubprocessError) as e:
            return None, f"ps: {e}"
    return read_ps(text), None


def _start_herdr(ctx, session):
    """Start this herdr session's pane list and agent list in the pool (once per refresh); returns its key in
    ctx.views. A herdr object passed in serves every session."""
    key = None if ctx.herdr else session
    if key not in ctx.views:
        client = ctx.herdr or Herdr(session)
        ctx.views[key] = [ctx.pool.submit(client.run, "pane", "list", timeout=5),
                          ctx.pool.submit(client.run, "agent", "list", timeout=5)]
    return key


def _herdr_view(ctx, session):
    """The panes (label -> pane id) and agents of one herdr session, or None when herdr does not answer."""
    key = _start_herdr(ctx, session)
    if isinstance(ctx.views[key], list):
        panes, agents = ctx.views[key]
        try:
            panes, agents = panes.result().get("panes", []), agents.result().get("agents", [])
            ctx.views[key] = {"panes": {p["label"]: p["pane_id"] for p in panes if p.get("label")},
                              "by_pane": {a["pane_id"]: a for a in agents if a.get("pane_id")},
                              "by_name": {a["name"]: a for a in agents if a.get("name")}}
        except Exception as e:     # herdr's CLI, a timeout or a fake can fail in any way; the row shows "?"
            ctx.errors.append(f"herdr {session}: {e}")
            ctx.views[key] = None
    return ctx.views[key]


def _herdr_status(view, agent_name):
    """The scheduler's match: the pane labelled with the agent name, then that pane's agent; the agent's own name
    only when no pane carries the label."""
    if view is None:
        return "?"
    pane = view["panes"].get(agent_name)
    agent = view["by_pane"].get(pane) if pane else view["by_name"].get(agent_name)
    return (agent.get("agent_status") or "unknown") if agent else "absent"


def _sig(path):
    """A file's (mtime_ns, size), the key the deck's caches are kept under; None when it cannot be stat'ed."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


def _messages(ctx, db_path):
    """Reuse the window/waiting summary while db/WAL stats and the minute are unchanged; recompute as time moves
    the hourly buckets, "today" and the SQL window."""
    sig = (_sig(db_path), _sig(f"{db_path}-wal"), int(ctx.now // 60))
    hit = ctx.cache.mail.get(str(db_path))
    if not hit or hit[0] != sig:
        value, summary = _incremental_messages(Path(db_path), ctx.now, hit[2] if hit else None)
        hit = ctx.cache.mail[str(db_path)] = (sig, value, summary)
    return hit[1]


def _role(t2, s):
    t = t2.t
    if s.key == "orc":
        return "orc"
    if s.kind == "lane":
        return "lane"
    if str(t.assistants.get(s.key, {}).get("role", "")).lower() == "designer":
        return "designer"
    return "guard" if s.key == t.guard else "builder" if s.key == t.builder else "assistant"


def _mail_cell(messages, key, now):
    if not messages:
        return None
    by = messages["by_target"].get(key, {})
    oldest = _epoch(by.get("oldest_waiting_ts"))
    oldest_mail = _epoch(by.get("oldest_mail_ts"))
    return {"waiting": by.get("waiting", 0), "held": by.get("held", 0),
            "delivered_today": by.get("delivered_today", 0), "oldest_waiting_s": None if oldest is None else now - oldest,
            "broadcasts": by.get("broadcasts", 0), "oldest_mail_s": None if oldest_mail is None else now - oldest_mail}


def _recent_index(messages):
    """The recent messages' positions by target and by sender: one pass over them per team, not per session."""
    to, by = {}, {}
    for i, m in enumerate((messages or {}).get("recent", [])):
        to.setdefault(m["target"], []).append(i)
        by.setdefault(m["sender"], []).append(i)
    return to, by


def _recent_messages(messages, index, s):
    """The session's five newest recent messages: in when it is the target, else out when it sent them."""
    to, by = index
    out = []
    for i in sorted({*to.get(s.key, ()), *by.get(s.display, ())})[:5]:
        m = messages["recent"][i]
        direction, peer = ("in", m["sender"]) if m["target"] == s.key else ("out", m["recipient"])
        out.append({"ts": m["ts"], "dir": direction, "peer": peer, "kind": m["kind"], "text": m["text"]})
    return out


def _idle_exit(tm, key, status, since, mail, now):
    """Seconds until the loop ends an idle session: only for one herdr shows idle or done, that is not kept awake,
    with nothing waiting for it."""
    if status not in ("idle", "done") or key in tm.keep_awake or not tm.t2.idle_exit_min or since is None \
            or (mail and mail["waiting"]):
        return None
    return max(0.0, tm.t2.idle_exit_min * 60 - (now - since))


def _metrics_candidates(ctx, s, root, cwd=None):
    """Log basenames mapped to seat roots, launch folders before transcript cwd folders; the first name wins."""
    folders = [(str(s.cwd), root or str(s.cwd)), (root, root or str(s.cwd))]
    if cwd:
        cwd_root = _worktree_root(ctx.cache, cwd) or cwd
        folders.extend(((cwd, cwd_root), (cwd_root, cwd_root)))
    candidates = {}
    for folder, seat_root in folders:
        if folder:
            candidates.setdefault(Path(folder).name, seat_root)
    return candidates


def _find_metrics(ctx, s, root, sid, cwd=None):
    """(log path, newest record, seat root) from launch and transcript-cwd candidates. Duplicate basenames are read
    once; the earlier candidate wins ties. A record without a timestamp loses to any dated record."""
    records = []
    for name, seat_root in _metrics_candidates(ctx, s, root, cwd).items():
        log = ctx.metrics / f"{name}.jsonl"
        m = read_metrics(log, sid, ctx.cache)
        if m:
            records.append((log, m, seat_root))
    return max(records, key=lambda row: row[1]["ts"] if row[1]["ts"] is not None else float("-inf"),
               default=(None, None, None))


def _session_sources(ctx, s, rec, root):
    """What a session row takes from its files: the status-line record and seat cost, the transcript's turn state,
    tools, tool trace and per-turn tokens, its compactions and its subagents."""
    sid = rec.get("sid")
    log, m, seat_root = _find_metrics(ctx, s, root, sid) if sid else (None, None, None)
    path = _find_transcript(ctx, rec, m)
    info = _transcript_info(path, ctx.cache) if path else None
    if sid and info and info["cwd"]:
        # With stable files, the first pass is also the answer unless cwd adds a new log basename.
        if _metrics_candidates(ctx, s, root, info["cwd"]).keys() - _metrics_candidates(ctx, s, root).keys():
            log, m, seat_root = _find_metrics(ctx, s, root, sid, info["cwd"])
    src = {"metrics": m, "info": info,
           "agents": read_subagents(Path(path).with_suffix(""), ctx.now, ctx.cache) if path else []}
    if m:
        # Compactions are rare and only counted, so the spec reads them every 30 s.
        src["compactions"] = ctx.cache.every(("compactions", path), ctx.now, 30,
                                             lambda: count_compactions(path, ctx.cache)) if path else (None, False)
        src["seat_today_usd"] = seat_cost_today(log, ctx.now, ctx.cache, seat_root)
        src["seat_today_partial"] = ctx.cache.follow[("metrics", str(log))]["partial"]
    return src


def _metric_cells(src, now):
    """Model, effort, context, cache and cost cells from the session's status-line record; the cache's time to
    expiry is counted from now, so it stays exact between reads of the log."""
    m = src["metrics"]
    if not m:
        return {"model": None, "effort": None, "context": None, "cache": None, "cost": None}
    compactions, partial = src["compactions"]
    expires = m["cache_expires_at"]
    return {"model": m["model"], "effort": m["effort"],
            "context": {"used_pct": m["used_pct"], "window": m["window"], "compactions": compactions,
                        "compactions_partial": partial},
            "cache": {"warm": m["cache_warm"], "hit_ratio": m["hit_ratio"],
                      "expires_in_s": None if expires is None else max(0, expires - now)},
            "cost": {"session_usd": m["cost_usd"], "seat_today_usd": src["seat_today_usd"],
                     "seat_today_partial": src["seat_today_partial"]}}


def _turn_cells(info, metrics):
    """Output tokens per turn (a compaction as {"compacted": True}) and the turns-left estimate against the
    status-line record's window."""
    turns = info["turns"] if info else []
    return {"turns": [t if "compacted" in t else t["output"] for t in turns],
            "turns_left": turns_left(turns, metrics["window"] if metrics else None)}


def _session_row(ctx, tm, s, rec, status, since):
    sid = rec.get("sid")
    root = _worktree_root(ctx.cache, str(s.cwd))
    # Refresh transcript state, status-line metrics and subagents every 5 s (the spec's cadence), per session
    # and session id; unchanged tails are cached and a new sid is checked at once. Herdr's status and state.json
    # fields are this refresh's.
    src = ctx.cache.every(("session", tm.t2.product, s.key, sid), ctx.now, 5,
                          lambda: _session_sources(ctx, s, rec, root))
    info = src["info"]
    mail = _mail_cell(tm.messages, s.key, ctx.now)
    return {"team": tm.t2.product, "key": s.key, "name": s.display, "role": _role(tm.t2, s), "agent": s.agent,
            "cwd": str(s.cwd), "worktree": root, "sid": sid, "herdr": {"status": status, "since": since},
            "transcript_state": info["state"] if info else "?", "transcript_mtime": info["mtime"] if info else None,
            **_metric_cells(src, ctx.now), "mail": mail, "draft_since": rec.get("draft_since"),
            "api_error": rec.get("api_error"),
            "idle_exit_in_s": _idle_exit(tm, s.key, status, since, mail, ctx.now),
            "recent": {"tools": info["tools"] if info else [], "trace": info["trace"] if info else [],
                       "messages": _recent_messages(tm.messages, tm.recent, s)},
            **_turn_cells(info, src["metrics"]),
            # Copies: model.derive writes each agent's flags into its dict, and src is reused by later snapshots.
            "agents": [dict(a) for a in src["agents"]]}


def _listed(rec, status, now):
    """A session herdr shows, or one that ended within the hour and has a session id."""
    return status != "absent" or bool(rec.get("sid") and now - (rec.get("state_since") or 0) < RECENT_END_S)


def _load_team(cache, path):
    """(v1 Team, codeteam2 Team or None), rebuilt when the manifest changes. codeteam2's Team creates team/v2/launch
    in its constructor, so it is built only once that folder exists; before that the team is on v1."""
    mtime = path.stat().st_mtime_ns
    entry = cache.teams.get(str(path))
    if not entry or entry["mtime"] != mtime:
        entry = cache.teams[str(path)] = {"mtime": mtime, "v1": v1.Team(path), "t2": None}
    if entry["t2"] is None and (entry["v1"].home / "v2" / "launch").is_dir():
        entry["t2"] = Team(path)
    return entry["v1"], entry["t2"]


def _team_sessions(cache, path, t2):
    """(t2.sessions(), t2.keep_awake()), listed again when team.json's (mtime_ns, size) changes or it cannot be stat'ed:
    both come from the manifest (its change rebuilds the whole entry, _load_team) and team.json. A lane repo's name
    comes from its git config, which is not watched: a changed origin shows after team.json or the manifest
    next changes."""
    entry = cache.teams[str(path)]
    sig = _sig(t2.t.team_file)
    if entry.get("sessions", (None,))[0] != sig or sig is None:
        with _no_git():
            entry["sessions"] = (sig, t2.sessions(), t2.keep_awake())
    return entry["sessions"][1:]


def _state_file(cache, path):
    """read_state, parsed again only when the file's (mtime_ns, size) changed (always, when it cannot be stat'ed)."""
    sig = _sig(path)
    hit = cache.states.get(str(path))
    if not hit or hit[0] != sig or sig is None:
        hit = cache.states[str(path)] = (sig, read_state(path))
    return hit[1]


def _v2_team(ctx, path, v1t, t2):
    # state.json every refresh (the spec's 2 s), parsed only when it changed.
    state = _state_file(ctx.cache, t2.dir / "state.json") or {}
    # Check messages.db every 5 s, the spec's cadence; _messages reuses the summary while db/WAL stats and minute match.
    messages = ctx.cache.every(("messages", str(t2.dir)), ctx.now, 5, lambda: _messages(ctx, t2.dir / "messages.db"))
    sessions, keep_awake = _team_sessions(ctx.cache, path, t2)
    tm = SimpleNamespace(t2=t2, messages=messages, recent=_recent_index(messages), keep_awake=keep_awake)
    view = _herdr_view(ctx, t2.herdr_session)
    rows = []
    for s in sessions:
        rec = state.get(s.key) or {}
        status = _herdr_status(view, s.agent)
        if _listed(rec, status, ctx.now):
            since = rec.get("state_since") if rec.get("status") == status else None
            rows.append(_session_row(ctx, tm, s, rec, status, since))
    running = [r for r in rows if r["herdr"]["status"] not in ("absent", "?")]
    return {"name": t2.product, "manifest": str(path), "home": str(v1t.home), "root": str(v1t.root),
            **team_flags(v1t.home, ctx.now), "cap": t2.cap, "running": len(running),
            "lanes_running": sum(r["role"] == "lane" for r in running),
            "mail_waiting": messages and messages["queued"] + messages["held"],
            "broadcasts_waiting": messages and messages["broadcasts_waiting"],
            "msgs_last_hour": messages and messages["last_hour"],
            "messages": messages and {k: v for k, v in messages.items() if k != "recent"},
            "disk": _state_file(ctx.cache, t2.dir / "deck" / "disk.json"), "sessions": rows}


def _team_row(ctx, path):
    try:
        v1t, t2 = _load_team(ctx.cache, path)
        if t2:
            row = _v2_team(ctx, path, v1t, t2)
        else:
            row = {"name": v1t.product, "manifest": str(path), "home": str(v1t.home), "root": str(v1t.root),
                   "state": "v1", "heartbeat_age_s": None, "cap": None, "running": 0, "lanes_running": 0,
                   "mail_waiting": None, "msgs_last_hour": None, "messages": None, "disk": None, "sessions": []}
    except (Exception, SystemExit) as e:      # a manifest or team that will not load is a row, not a crash
        return {"name": path.stem, "manifest": str(path), "state": "?", "error": str(e), "sessions": []}
    row["free_gb"] = _free_gb(v1t.root)
    return row


def _builds(ctx, teams, ps):
    sessions = [s for t in teams for s in t["sessions"]]
    agents = [a for s in sessions for a in s["agents"] if a["worktree"]]
    watched = sorted({w for s in sessions for w in (s["worktree"], s["cwd"]) if w} | {a["worktree"] for a in agents})
    disk_worktrees = [w for t in teams for w in (t.get("disk") or {}).get("worktrees", [])]
    # Warms are looked for in every worktree a session or a running subagent works in, and in those the last disk
    # scan found; the result is reused for 10 s, since a warm lasts minutes.
    warm_set = sorted({s["worktree"] for s in sessions if s["worktree"]}
                      | {a["worktree"] for a in agents if not a["finished"]}
                      | {w["path"] for w in disk_worktrees})
    warms = ctx.cache.every("warms", ctx.now, 10, lambda: [
        w for w in (read_warm(wt, ctx.alive, ctx.now) for wt in warm_set) if w])
    build_dirs = ({"path": w["path"], "part": p, "size_gb": gb} for w in disk_worktrees
                  for p, gb in w.get("parts", {}).items() if p in model.BUILD_PARTS)
    # The queue and the runner's state every 5 s: the cadence of the ps their pids are checked against.
    queue = ctx.cache.every("queue", ctx.now, 5, lambda: read_queue(ctx.queue, ctx.queue_conf, ctx.alive, ctx.now))
    return {"queue": queue, "warms": warms, "largest": sorted(build_dirs, key=lambda b: -b["size_gb"])[:5],
            "procs": _procs(ctx.cache, ps, watched)}


def _procs(cache, ps, watched):
    """worktree -> pids of its build processes; None when ps did not answer, so no agent is called stalled.
    Worked out again only when ps ran again (it is the same dict between its runs) or the watched set changed.
    ps lists about 1 MB of args (some shell commands are tens of KB) and a process usually lives across many ps
    runs, so each (pid, args) is tested for BUILD_TOOLS once, and a build-tool line is given to build_procs once
    per worktree."""
    if ps is None:
        return None
    if cache.procs is None or cache.procs[0] is not ps or cache.procs[1] != watched:
        cache.proc_matches = {(pid, p["args"]): _line_matches(cache.proc_matches, pid, p, watched)
                              for pid, p in ps.items()}
        tools = [(pid, m) for (pid, _), m in cache.proc_matches.items() if m is not None]
        cache.procs = (ps, watched, {wt: [pid for pid, m in tools if m[wt]] for wt in watched})
    return cache.procs[2]


def _line_matches(seen, pid, p, watched):
    """One ps line's Cache.proc_matches entry: None when its args name no build tool, else whether build_procs
    matches it, per watched worktree. seen holds the last ps run's entries; only what they lack is worked out."""
    key = (pid, p["args"])
    known = seen[key] if key in seen else ({} if any(t in p["args"] for t in BUILD_TOOLS) else None)
    for wt in () if known is None else watched:
        if wt not in known:
            known[wt] = bool(build_procs({pid: p}, wt))
    return known


def collect(names=(), *, teams_dir=None, now=None, herdr=None, ps_text=None, queue_dir=None,
            queue_conf=None, metrics_dir=None, projects_dir=None, cache=None, thresholds=None, disk=None):
    """One snapshot of the named teams (all of teams_dir/*.toml when none are named) with model.derive's flags and
    alerts. Every directory defaults to the live one; tests over a fixture pass their own. disk is a
    DiskScanner.result(): its entry for a team replaces what the team's disk.json says (and gives a team with no
    v2 folder its disk). ps (when its 5 s interval is due), and the pane and agent lists of the default herdr session
    (or of `herdr` when given), run in threads while the teams load; a team in another session fetches its own.
    queue_dir is the build queue's folder (else $CODETEAM_QUEUE_DIR, else run/queue under CT_HOME) and queue_conf its
    config (else $CODETEAM_QUEUE_CONF, else queue.toml in the folder's parent); the runner's state is read from
    queue-runner.json in the folder's parent."""
    started = time.monotonic()
    now = time.time() if now is None else now
    cache = cache or Cache()
    cache.clock = now
    errors = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        ctx = SimpleNamespace(
            now=now, cache=cache, herdr=herdr, views={}, errors=errors, pool=pool, alive=None,
            projects=Path(projects_dir or Path.home() / ".claude" / "projects"), project_dirs=None,
            metrics=Path(metrics_dir or os.environ.get("CLAUDE_METRICS_DIR") or os.environ.get("CODETEAM_METRICS_DIR")
                         or WORKSPACE / "metrics"),
            queue=Path(queue_dir or os.environ.get("CODETEAM_QUEUE_DIR") or CT_HOME / "run" / "queue"))
        ctx.queue_conf = Path(queue_conf or os.environ.get("CODETEAM_QUEUE_CONF") or ctx.queue.parent / "queue.toml")
        # ps every 5 s, the spec's cadence; a ps_text the caller gives is always the one parsed.
        ps_job = pool.submit(_read_ps, ps_text) if ps_text is not None else \
            ctx.cache.every("ps", now, 5, lambda: pool.submit(_read_ps, None))
        _start_herdr(ctx, DEFAULT_HERDR_SESSION)
        manifests = sorted(Path(teams_dir or CT_HOME / "teams").glob("*.toml"))
        teams = [_team_row(ctx, p) for p in manifests if not names or p.stem in names]
        ps, ps_error = ps_job.result()
        if ps_error:
            errors.append(ps_error)
        ctx.alive = None if ps is None else set(ps)
        for team in teams:
            team["disk"] = ((disk or {}).get("teams") or {}).get(team["name"]) or team.get("disk")
        disks = [t["disk"]["at"] for t in teams if t.get("disk") and t["disk"].get("at")]
        snap = {"version": 1, "at": now, "took_s": 0.0, "errors": errors,
                "volume": {"free_gb": next((t["free_gb"] for t in teams if t.get("free_gb") is not None), None)},
                "teams": teams, "builds": _builds(ctx, teams, ps), "disk_at": max(disks, default=None), "alerts": []}
    cache.prune(now)
    snap["took_s"] = round(time.monotonic() - started, 3)
    return model.derive(snap, now, thresholds)
