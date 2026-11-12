"""The message store: every message between sessions, durable and searchable.

The interface the rest of codeteam2 uses is the Store's public methods: add, get, pending, mark,
settle_held, release, drop, recent, after, counts. A queue-backed store could replace this class by
offering the same methods; nothing else reads the database directly.

Shaped like a queue item (id, queue, sender, recipient, kind, body, state, timestamps)
so the transport can move to a push-capable server (queue items delivered by MCP push, once one supports
push) without the rest of codeteam v2 changing. Until then the store is a SQLite file in the
team's folder and delivery is herdr's `agent prompt` (see scheduler.py).

States: queued (waiting for its recipient to be ready), delivered (handed to the session),
held (refused by the recipient, or prompted three times without starting a turn; it waits for a change),
dropped (a person or codeteam gave up).
Held mail returns to queued when the recipient's herdr status changes, it completes a turn, the loop
starts, or its no-turn episode ends when state_change_seq moves. If a later [codeteam]
prompt in its transcript ends the episode, held messages its headers name are settled as delivered without
another attempt; only the rest are released. A person can drop held mail.

flags is a bitmap of per-message facts (bit assignments below); a bit, once assigned, keeps its meaning.

A ride-along message (ride = 1) never starts or wakes its recipient: it waits and goes with the
next prompt that delivers something else (codeteam's own reports, such as patrol's; the spend
analysis, 2026-10-25: report stalls without waking the orchestrator each time).
"""
from collections.abc import Iterable
import datetime as dt
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    channel      TEXT NOT NULL,
    sender       TEXT NOT NULL,
    kind         TEXT NOT NULL,
    recipient    TEXT NOT NULL,
    target       TEXT NOT NULL,
    body         TEXT NOT NULL,
    state        TEXT NOT NULL DEFAULT 'queued',
    attempts     INTEGER NOT NULL DEFAULT 0,
    delivered_at TEXT,
    note         TEXT
);
CREATE INDEX IF NOT EXISTS messages_target_state ON messages(target, state);
"""

# A runtime command (/compact, the resume line, /exit) travels as a message of this kind:
# delivered exactly like a message, but its body is typed as is.
RUNTIME = "RUNTIME"

# flags bits. Assigned: bit 0. Never reuse a bit, never bit 63.
# bit 0: the orchestrator has been told this message's prompts started no turn ("could not get #N").
#        Set on the row so a message is named in a NOTE once, across releases and loop restarts; an episode
#        whose messages all carry it posts no NOTE.
FLAG_NO_TURN_NOTED = 1 << 0


def now():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path, log_path: Path = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path = Path(log_path) if log_path else self.path.with_name("messages.log")
        self.db = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(messages)")}
        if "ride" not in cols:          # stores made before ride-along messages (2026-10-25)
            self.db.execute("ALTER TABLE messages ADD COLUMN ride INTEGER NOT NULL DEFAULT 0")
        if "flags" not in cols:         # stores made before the flags bitmap (2026-10-29): no bit set
            try:
                self.db.execute("ALTER TABLE messages ADD COLUMN flags INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError as e:
                # Two processes opening an old store at once both see no column; the second ALTER loses.
                if "duplicate column" not in str(e):
                    raise

    def add(self, channel, sender, kind, recipient, target, body, ride=False):
        cur = self.db.execute(
            "INSERT INTO messages (ts, channel, sender, kind, recipient, target, body, ride) VALUES (?,?,?,?,?,?,?,?)",
            (now(), channel, sender, kind.upper(), recipient, target, body, 1 if ride else 0))
        mid = cur.lastrowid
        if kind.upper() != RUNTIME:
            with self.log_path.open("a") as f:
                f.write(f"{now()[:16].replace('T', ' ')} | #{mid} | {sender} | {kind.upper()} {recipient} | "
                        f"{' '.join(body.split())}\n")
        return mid

    def get(self, mid):
        return self.db.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()

    def pending(self, target=None, held=False):
        """Messages not yet delivered, oldest first: queued ones (the loop's to deliver), and with held=True
        held ones too (for counting what waits and settling mail named by a prompt that ran)."""
        q = "SELECT * FROM messages WHERE state IN ('queued','held')" if held else \
            "SELECT * FROM messages WHERE state='queued'"
        args = ()
        if target:
            q += " AND target=?"
            args = (target,)
        return self.db.execute(q + " ORDER BY id", args).fetchall()

    def mark(self, mid, state, note=None, flags=0, only_from=None):
        """Set a message's state (delivered and held count as an attempt). flags: bits to set (ORed in).
        only_from: apply only while the row is in that state, so a change another process made since the
        caller read the row (a drop) is not overwritten. Returns True when a row changed."""
        where, args = " WHERE id=?", [mid]
        if only_from is not None:
            where += " AND state=?"
            args.append(only_from)
        if state == "delivered":
            sql, vals = ("UPDATE messages SET state=?, delivered_at=?, attempts=attempts+1, note=?, flags=flags|?",
                         [state, now(), note, flags])
        elif state == "queued":
            sql, vals = "UPDATE messages SET state=?, note=?, flags=flags|?", [state, note, flags]
        else:
            sql, vals = ("UPDATE messages SET state=?, attempts=attempts+1, note=?, flags=flags|?",
                         [state, note, flags])
        return self.db.execute(sql + where, (*vals, *args)).rowcount > 0

    def settle_held(self, target: str, mids: Iterable[int], note: str) -> list[int]:
        """Mark the target's held rows among mids delivered and return their ids in ascending order.
        Set delivered_at and note without incrementing attempts: the prompt has already been counted."""
        settled = []
        for mid in sorted(mids):
            if self.db.execute("UPDATE messages SET state='delivered', delivered_at=?, note=? "
                               "WHERE id=? AND target=? AND state='held'", (now(), note, mid, target)).rowcount:
                settled.append(mid)
        return settled

    def release(self, target, note):
        """Put a session's held messages back in the queue (something changed for it); their ids, oldest first."""
        mids = [r["id"] for r in self.db.execute("SELECT id FROM messages WHERE target=? AND state='held' ORDER BY id",
                                                 (target,))]
        for mid in mids:
            self.db.execute("UPDATE messages SET state='queued', note=? WHERE id=? AND state='held'", (note, mid))
        return mids

    def recent(self, target=None, limit=20):
        q, args = "SELECT * FROM messages WHERE kind != ?", [RUNTIME]
        if target:
            q += " AND (target=? OR sender=?)"
            args += [target, target]
        rows = self.db.execute(q + " ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()
        return list(reversed(rows))

    def after(self, mid):
        """Team messages (not runtime commands) newer than mid, oldest first: for following live."""
        return self.db.execute("SELECT * FROM messages WHERE id > ? AND kind != ? ORDER BY id",
                               (mid, RUNTIME)).fetchall()

    def drop(self, mids, note, awaiting=()):
        """Give up on messages (a person's decision): they leave the queue and stay on record. Queued and held
        messages are dropped, and a delivered one whose id is in awaiting (prompted, its turn not yet seen;
        the caller clears it from the session's state). Returns {mid: "dropped" or why it was not}, one entry
        per distinct id (a repeated id is dropped once); a row not dropped is left as it was. The UPDATE
        carries the state it read, so a row another process changed in between is reported, not overwritten."""
        out = {}
        for mid in dict.fromkeys(mids):
            m = self.get(mid)
            if not m:
                out[mid] = "not dropped: no such message"
                continue
            if m["state"] in ("queued", "held") or (m["state"] == "delivered" and mid in awaiting):
                cur = self.db.execute("UPDATE messages SET state='dropped', note=? WHERE id=? AND state=?",
                                      (note, mid, m["state"]))
                if cur.rowcount:
                    out[mid] = "dropped"
                    continue
                m = self.get(mid)       # changed since the read above: report what it is now
            if m["state"] == "delivered":
                out[mid] = "not dropped: delivered and its turn has run (the session has it)"
            else:
                out[mid] = f"not dropped: already {m['state']}"
        return out

    def counts(self):
        rows = self.db.execute("SELECT target, state, COUNT(*) n FROM messages GROUP BY target, state").fetchall()
        out = {}
        for r in rows:
            out.setdefault(r["target"], {})[r["state"]] = r["n"]
        return out
