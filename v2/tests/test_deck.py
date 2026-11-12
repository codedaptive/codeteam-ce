"""Tests for the deck (codeteam2 deck): the collectors over fixture files, the flags and alerts, the screen drawn
from a fixture snapshot, the `deck` subcommand and its --pane, and collect() over a fixture team folder.

Every path is a tempdir fixture, herdr is a fake and ps is text: no live team, no herdr, no git, no network.
The deck modules are imported inside each class's setUp, so a class whose module is missing fails on its own.
"""
import builtins
import contextlib
import copy
import datetime as dt
import gc
import io
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import tracemalloc
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2.herdr import Herdr, HerdrError  # noqa: E402

# 15:00 local on 2026-11-02. "Today" in the messages fixture starts at local midnight.
NOW = dt.datetime(2026, 11, 2, 15, 0).astimezone().timestamp()
MIN = 60
HOUR = 3600
SPARK_CHARS = " ▁▂▃▄▅▆▇█"
# The build queue's environment knobs; a queue test clears them (clear_queue_env) so the shell never leaks in.
QUEUE_ENV = ("CODETEAM_QUEUE_DIR", "CODETEAM_QUEUE_CONF", "CODETEAM_BUILD_BUDGET", "CODETEAM_BUILDQ_STALE",
             "CODETEAM_BUILDQ_LOAD_FILE")
# queue.toml in the layout zone/docs/INTERFACE.md gives. budget, load_max and swap_max are top-level keys the deck
# must ignore: the runner's state carries them, not the config.
QUEUE_TOML = """budget = 6
load_max = 36
swap_max = 0.9
retention_hours = 24

[classes.full]
guaranteed = 1
ceiling = 1

[classes.post]
guaranteed = 1
ceiling = 2

[classes.pre]
guaranteed = 1
ceiling = 2

[classes.dev]
guaranteed = 1
ceiling = 0
"""
# What read_queue_config gives when queue.toml says nothing: zone's defaults (INTERFACE.md, "queue.toml").
ZONE_DEFAULTS = {"retention_hours": 24,
                 "classes": {"full": {"guaranteed": 1, "ceiling": 1}, "post": {"guaranteed": 1, "ceiling": 2},
                             "pre": {"guaranteed": 1, "ceiling": 2}, "dev": {"guaranteed": 1, "ceiling": 0}}}
# A ps listing in which the build queue's runner (pid 111) is alive.
PS_RUNNER = "  111 00:10 codeteam-buildq\n"
RUNNER_KEYS = {"state", "pid", "beat_age_s", "budget", "used", "load", "load_max", "swap", "swap_max", "load_hold",
               "swap_hold"}


def iso(ts):
    return dt.datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def epoch(text):
    return dt.datetime.fromisoformat(text).timestamp()


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def job(ticket, cls="full", state="queued", **fields):
    """A job file's contents: the runner's JSON fields, times in epoch seconds."""
    return {"ticket": ticket, "class": cls, "state": state, **fields}


def put_job(queue, name, row):
    """Writes row as <name>.json under queue, as the runner does. The deck only reads it."""
    queue.mkdir(parents=True, exist_ok=True)
    path = queue / f"{name}.json"
    path.write_text(json.dumps(row))
    return path


def tickets(rows):
    return [r["ticket"] for r in rows]


def queue_class(queue, name):
    """The class row named name in a queue dict (builds["queue"] or read_queue's result)."""
    return next(c for c in queue["classes"] if c["class"] == name)


def clear_queue_env(test):
    """Removes the build queue's environment knobs for the test's span (patch.dict restores os.environ after it)."""
    patcher = patch.dict(os.environ)
    patcher.start()
    test.addCleanup(patcher.stop)
    for key in QUEUE_ENV:
        os.environ.pop(key, None)


RUNNER_FIELDS = {"pid": 111, "beat": NOW - 5, "budget": 6, "used": 1.5, "load": 2.0, "load_max": 36, "swap": 0.1,
                 "swap_max": 0.9, "load_hold": False, "swap_hold": False}


def write_runner(path, **fields):
    """queue-runner.json as the runner writes it (RUNNER_FIELDS, with the given fields replaced)."""
    path.write_text(json.dumps({**RUNNER_FIELDS, **fields}))
    return path


def seed_messages(store):
    """Mail around NOW, in creation order (= id order = time order): one from yesterday, a held and a queued
    message, two delivered today (one a broadcast to ALL, one with a long body), and a runtime command that
    no count may include."""
    from codeteam2.store import RUNTIME

    def put(ts, sender, recipient, target, state="delivered", delivered=None, body="a note"):
        mid = store.add("general", sender, "REQUEST", recipient, target, body)
        store.db.execute("UPDATE messages SET ts=?, state=?, delivered_at=? WHERE id=?",
                         (iso(ts), state, iso(delivered) if delivered else None, mid))
        return mid

    ids = {
        "old": put(NOW - 29 * HOUR, "Old", "Coord-a", "a", delivered=NOW - 29 * HOUR),
        "held": put(NOW - 150 * MIN, "Orc", "Coord-b", "b", state="held"),
        "queued": put(NOW - 110 * MIN, "Orc", "Coord-a", "a", state="queued"),
        "direct": put(NOW - 45 * MIN, "Coord-a", "Orc", "orc", delivered=NOW - 44 * MIN,
                      body="line one\n\n   line   two " + "x" * 200),
        "broadcast": put(NOW - 30 * MIN, "Kong", "ALL", "orc", delivered=NOW - 29 * MIN),
    }
    ids["runtime"] = store.add("runtime", "codeteam", RUNTIME, "Coord-a", "a", "/compact")
    store.db.execute("UPDATE messages SET ts=?, state='queued' WHERE id=?", (iso(NOW - 5 * MIN), ids["runtime"]))
    return ids


class CollectTests(unittest.TestCase):
    """collect.py: each reader on fixture files. A failing source gives None or "?", never an exception."""

    def setUp(self):
        from codeteam2.deck import collect
        self.c = collect
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def _mail(self):
        from codeteam2.store import Store
        path = self.root / "mail" / "messages.db"
        store = Store(path)
        self.addCleanup(store.db.close)
        return path, seed_messages(store), store

    def _transcript(self, rel):
        path = self.root / "projects" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n")
        return path

    def test_parse_etime_reads_mm_ss_hh_mm_ss_and_days(self):
        self.assertEqual(self.c.parse_etime("05:30"), 330)
        self.assertEqual(self.c.parse_etime("01:02:03"), 3723)
        self.assertEqual(self.c.parse_etime("2-03:04:05"), 183845)

    def test_read_ps_skips_the_header_and_bad_lines(self):
        ps = self.c.read_ps(
            "  PID     ELAPSED ARGS\n"
            " 1201       05:30 cargo build --manifest-path /a/wt/Cargo.toml\n"
            " 1202  1-02:00:00 /bin/zsh -l\n"
            " nonsense here\n")
        self.assertEqual(sorted(ps), [1201, 1202])
        self.assertEqual(ps[1201]["etime_s"], 330)
        self.assertEqual(ps[1201]["args"], "cargo build --manifest-path /a/wt/Cargo.toml")
        self.assertEqual(ps[1202]["etime_s"], 93600)

    def test_build_procs_matches_the_worktree_path_and_not_a_longer_name(self):
        ps = self.c.read_ps(
            "  PID ELAPSED ARGS\n"
            " 1201 05:30 cargo build --manifest-path /a/wt/Cargo.toml\n"
            " 1202 00:10 rustc --crate-name x /a/wt2/src/lib.rs\n"
            " 1203 02:00 make -C /a/wt\n"
            " 1204 01:00 cargo test /a/wt --release\n")
        procs = self.c.build_procs(ps, "/a/wt")
        self.assertEqual(sorted(p["pid"] for p in procs), [1201, 1203, 1204])
        self.assertEqual(next(p for p in procs if p["pid"] == 1201)["etime_s"], 330)

    def test_tail_records_drops_the_partial_first_line(self):
        path = self.root / "log.jsonl"
        lines = [json.dumps({"i": i, "pad": "x" * 40}) for i in range(10)]
        path.write_text("\n".join(lines) + "\n")
        # A window that starts 5 bytes before the start of record 7: the cut record 6 is dropped.
        window = sum(len(x) + 1 for x in lines[7:]) + 5
        self.assertEqual([r["i"] for r in self.c.tail_records(path, nbytes=window)], [7, 8, 9])

    def test_tail_records_is_empty_when_unreadable(self):
        self.assertEqual(self.c.tail_records(self.root / "missing.jsonl"), [])

    def test_team_state_is_halted_up_down_or_unknown(self):
        cases = {"up": ["v2/up"], "down": ["v2/down"], "HALTED": ["v2/up", "HALTED"], "?": []}
        for want, files in cases.items():
            home = self.root / f"team-{want}" / "team"
            for rel in files:
                (home / rel).parent.mkdir(parents=True, exist_ok=True)
                (home / rel).touch()
            with self.subTest(want=want):
                self.assertEqual(self.c.team_flags(home, NOW)["state"], want)

    def test_heartbeat_age_is_the_file_age_and_none_when_missing(self):
        home = self.root / "team"
        (home / "v2").mkdir(parents=True)
        (home / "v2" / "up").touch()
        (home / "v2" / "heartbeat").write_text(str(int(NOW - 10)))
        self.assertEqual(self.c.team_flags(home, NOW)["heartbeat_age_s"], 10)
        (home / "v2" / "heartbeat").unlink()
        self.assertIsNone(self.c.team_flags(home, NOW)["heartbeat_age_s"])

    def test_transcript_path_uses_the_recorded_file_when_it_is_the_session_transcript(self):
        recorded = self.root / "elsewhere" / "s1.jsonl"
        recorded.parent.mkdir()
        recorded.write_text("{}\n")
        rec = {"sid": "s1", "transcript": str(recorded)}
        self.assertEqual(Path(self.c.transcript_path(rec, self.root / "projects")), recorded)

    def test_transcript_path_ignores_a_recorded_file_named_for_another_session(self):
        other = self.root / "elsewhere" / "other.jsonl"
        other.parent.mkdir()
        other.write_text("{}\n")
        mine = self._transcript("proj/s1.jsonl")
        rec = {"sid": "s1", "transcript": str(other)}
        self.assertEqual(Path(self.c.transcript_path(rec, self.root / "projects")), mine)

    def test_transcript_path_falls_back_to_the_projects_folders(self):
        mine = self._transcript("proj/s1.jsonl")
        self.assertEqual(Path(self.c.transcript_path({"sid": "s1"}, self.root / "projects")), mine)

    def test_transcript_path_is_none_without_a_transcript(self):
        self.assertIsNone(self.c.transcript_path({"sid": "s9"}, self.root / "projects"))

    def test_transcript_path_never_writes_the_record(self):
        self._transcript("proj/s1.jsonl")
        rec = {"sid": "s1"}
        self.c.transcript_path(rec, self.root / "projects")
        self.assertEqual(rec, {"sid": "s1"})

    def test_incremental_messages_match_full_summary_through_changes_and_replacements(self):
        from codeteam2.store import Store

        path = self.root / "messages.db"
        store = Store(path)
        self.addCleanup(lambda: store.db.close())
        midnight = dt.datetime.fromtimestamp(NOW).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        ctx = SimpleNamespace(now=midnight + 2 * HOUR, cache=self.c.Cache())
        old = store.add("general", "sender", "REQUEST", "person", "old", "old waiting")
        store.db.execute("UPDATE messages SET ts=?, state='held' WHERE id=?", (iso(ctx.now - 72 * HOUR), old))
        offset = store.add("general", "sender", "REQUEST", "person", "offset", "offset waiting")
        offset_text = dt.datetime.fromtimestamp(ctx.now - 23 * HOUR, dt.timezone(-dt.timedelta(hours=23))) \
            .isoformat(timespec="seconds")
        store.db.execute("UPDATE messages SET ts=?, delivered_at=?, state='queued' WHERE id=?",
                         (offset_text, offset_text, offset))
        since = dt.datetime.fromtimestamp(min(midnight, ctx.now - 86400) - 3 * HOUR).strftime("%Y-%m-%dT%H:%M:%S")
        self.assertLess(offset_text, since)
        result = self.c._messages(ctx, path)
        self.assertEqual(result, self.c.read_messages(path, ctx.now))
        self.assertEqual((result["held"], result["queued"], sum(result["hourly"])), (1, 1, 0))
        store.db.execute("UPDATE messages SET state='dropped' WHERE id=?", (old,))
        ctx.now += MIN
        result = self.c._messages(ctx, path)
        self.assertEqual(result, self.c.read_messages(path, ctx.now))
        self.assertNotIn("old", result["by_target"])

        returning = store.add("general", "sender", "REQUEST", "person", "returning", "clock rewind")
        store.db.execute("UPDATE messages SET ts=?, delivered_at=?, state='delivered' WHERE id=?",
                         (iso(midnight - 25 * HOUR), iso(midnight - 25 * HOUR), returning))
        self.assertEqual(self.c._messages(ctx, path), self.c.read_messages(path, ctx.now))
        ctx.now = midnight - 2 * HOUR
        result = self.c._messages(ctx, path)
        self.assertEqual(result, self.c.read_messages(path, ctx.now))
        self.assertGreaterEqual(sum(result["hourly"]), 1)

        ctx.now = NOW - 10 * HOUR
        rng = random.Random(52733)
        ids = []
        for step in range(320):
            ctx.now += -4 * HOUR if step == 150 else 11 * MIN
            if step % 2 == 0 or not ids:
                kind = ("RUNTIME", "RULING", "REQUEST", "NOTE")[step % 8 // 2]
                mid = store.add("general", rng.choice(("alpha", "beta", "gamma")), kind,
                                rng.choice(("all", "ALL", "All", "person")),
                                rng.choice(("a", "b", "c")), f"message {step}\n  body")
                ids.append(mid)
                timestamp = ctx.now + rng.choice((-30 * HOUR, -27 * HOUR, -24 * HOUR, -HOUR, 0, HOUR))
                if step == 2:
                    text = "not-a-time"
                elif step % 4 == 0:
                    text = dt.datetime.fromtimestamp(timestamp, dt.timezone(dt.timedelta(hours=5, minutes=30))) \
                        .isoformat(timespec="seconds")
                else:
                    text = iso(timestamp)
                store.db.execute("UPDATE messages SET ts=? WHERE id=?", (text, mid))
            else:
                mid = rng.choice(ids)
                action = step % 10
                if action == 1:
                    store.mark(mid, "held")
                elif action == 3:
                    store.mark(mid, "queued")
                elif action == 5:
                    store.mark(mid, "dropped")
                elif action == 7:
                    store.db.execute("UPDATE messages SET state='delivered', delivered_at=? WHERE id=?",
                                     (iso(ctx.now - rng.randrange(0, 30 * HOUR)), mid))
                else:
                    store.db.execute("UPDATE messages SET state='delivered', delivered_at=NULL, ts=? WHERE id=?",
                                     (iso(ctx.now - rng.randrange(0, 30 * HOUR)), mid))
            self.assertEqual(self.c._messages(ctx, path), self.c.read_messages(path, ctx.now), f"step {step}")

        store.db.close()
        for step, count in (("replaced", 8), ("rows vanished", 1)):
            replacement = self.root / f"{count}.db"
            other = Store(replacement)
            for i in range(count):
                other.add("general", "replacement", "REQUEST", "all", "a", f"replacement {i}")
            other.db.close()
            os.replace(replacement, path)
            ctx.now += MIN
            self.assertEqual(self.c._messages(ctx, path), self.c.read_messages(path, ctx.now), step)

    def _assert_message_cache_memory(self, old_count, recent_count, limit):
        from codeteam2.store import Store

        path = self.root / "memory.db"
        store = Store(path)
        old, recent = iso(NOW - 72 * HOUR), iso(NOW - HOUR)
        store.db.execute("BEGIN")
        store.db.executemany(
            "INSERT INTO messages (ts, channel, sender, kind, recipient, target, body, state, delivered_at) "
            "VALUES (?, 'general', 'sender', 'REQUEST', 'person', 'target', 'body', 'delivered', ?)",
            [(old, old)] * old_count + [(recent, recent)] * recent_count)
        store.db.execute("COMMIT")
        store.db.close()
        ctx = SimpleNamespace(now=NOW, cache=self.c.Cache())

        # Separate tracing runs count the same returned summary in each; subtracting the oracle's retained
        # allocations isolates the cache overhead, including rows held beyond the newest 200.
        gc.collect()
        tracemalloc.start()
        try:
            expected = self.c.read_messages(path, NOW)
            gc.collect()
            baseline = tracemalloc.get_traced_memory()[0]
        finally:
            tracemalloc.stop()
        gc.collect()
        tracemalloc.start()
        try:
            result = self.c._messages(ctx, path)
            gc.collect()
            retained = tracemalloc.get_traced_memory()[0]
        finally:
            tracemalloc.stop()
        self.assertEqual(result, expected)
        self.assertLess(retained - baseline, limit,
                        f"cache beyond summary: {retained - baseline} bytes; retained={retained}, "
                        f"baseline={baseline}, limit={limit}, old={old_count}, recent={recent_count}")

    def test_incremental_messages_cache_does_not_retain_old_delivered_rows(self):
        self._assert_message_cache_memory(5000, 20, 200_000)

    def test_incremental_messages_cache_is_compact_for_in_window_rows(self):
        self._assert_message_cache_memory(0, 2000, 2000 * 600)

    def test_incremental_messages_parse_only_changed_rows_after_insert(self):
        from codeteam2.store import Store

        path = self.root / "messages.db"
        store = Store(path)
        self.addCleanup(store.db.close)
        for i in range(500):
            store.add("general", "sender", "REQUEST", "recipient", "target", f"message {i}")
        store.db.execute("UPDATE messages SET ts=?", (iso(NOW - HOUR),))
        ctx = SimpleNamespace(now=NOW, cache=self.c.Cache())
        self.c._messages(ctx, path)
        store.add("general", "sender", "REQUEST", "recipient", "target", "new message")
        ctx.now += MIN
        with patch.object(self.c, "_epoch", wraps=self.c._epoch) as parse:
            result = self.c._messages(ctx, path)
        self.assertLessEqual(parse.call_count, 20)
        self.assertEqual(result, self.c.read_messages(path, ctx.now))

    def test_incremental_messages_reuse_same_object_without_opening_unchanged_db(self):
        path, _, _ = self._mail()
        ctx = SimpleNamespace(now=NOW, cache=self.c.Cache())
        first = self.c._messages(ctx, path)
        ctx.now += 1
        with patch.object(self.c.sqlite3, "connect", side_effect=AssertionError("database opened")):
            second = self.c._messages(ctx, path)
        self.assertIs(second, first)

    def test_messages_hourly_counts_the_last_24_hours_oldest_first(self):
        path, _, _ = self._mail()
        m = self.c.read_messages(path, NOW)
        self.assertEqual(len(m["hourly"]), 24)
        self.assertEqual(sum(m["hourly"]), 4)      # the 29 h old message and the runtime command are out
        self.assertEqual(m["hourly"][23], 2)       # direct and broadcast: the last hour
        self.assertEqual(m["hourly"][22], 1)       # queued, 110 min ago
        self.assertEqual(m["hourly"][21], 1)       # held, 150 min ago
        self.assertEqual(m["last_hour"], 2)

    def test_messages_today_counts_and_top_senders(self):
        path, _, _ = self._mail()
        m = self.c.read_messages(path, NOW)
        self.assertEqual(m["queued"], 1)
        self.assertEqual(m["held"], 1)
        self.assertEqual(m["delivered_today"], 2)
        self.assertEqual(m["broadcasts_today"], 1)
        top = [list(x) for x in m["top_senders"]]
        self.assertEqual(top[0], ["Orc", 2])
        self.assertNotIn("Old", [name for name, _ in top])

    def test_messages_last_ten_are_newest_first_with_text_cut_to_80(self):
        path, ids, _ = self._mail()
        m = self.c.read_messages(path, NOW)
        self.assertEqual([r["id"] for r in m["last"]],
                         [ids[k] for k in ("broadcast", "direct", "queued", "held", "old")])
        direct = next(r for r in m["last"] if r["id"] == ids["direct"])
        self.assertLessEqual(len(direct["text"]), 80)
        self.assertNotIn("\n", direct["text"])
        self.assertTrue(direct["text"].startswith("line one line two"), direct["text"])

    def test_messages_by_target_give_waiting_held_and_delivered_today(self):
        path, _, _ = self._mail()
        by = self.c.read_messages(path, NOW)["by_target"]
        self.assertEqual(by["a"]["waiting"], 1)
        self.assertEqual(by["a"]["held"], 0)
        self.assertEqual(by["a"]["delivered_today"], 0)
        self.assertEqual(epoch(by["a"]["oldest_waiting_ts"]), NOW - 110 * MIN)
        self.assertEqual(by["b"]["waiting"], 1)
        self.assertEqual(by["b"]["held"], 1)
        self.assertEqual(epoch(by["b"]["oldest_waiting_ts"]), NOW - 150 * MIN)
        self.assertEqual(by["orc"]["waiting"], 0)
        self.assertEqual(by["orc"]["delivered_today"], 2)
        self.assertIsNone(by["orc"]["oldest_waiting_ts"])

    def test_runtime_commands_are_not_counted(self):
        path, ids, _ = self._mail()
        m = self.c.read_messages(path, NOW)
        self.assertNotIn(ids["runtime"], [r["id"] for r in m["last"]])
        self.assertEqual(m["queued"], 1)
        self.assertEqual(m["by_target"]["a"]["waiting"], 1)

    def test_max_id_moves_when_mail_arrives(self):
        path, _, store = self._mail()
        before = self.c.read_messages(path, NOW)["max_id"]
        store.add("general", "Orc", "REQUEST", "Coord-a", "a", "one more")
        self.assertGreater(self.c.read_messages(path, NOW)["max_id"], before)

    def test_reading_a_wal_database_with_no_wal_file_leaves_the_folder_as_it_was(self):
        path, _, store = self._mail()
        store.db.close()
        for suffix in ("-wal", "-shm"):
            Path(f"{path}{suffix}").unlink(missing_ok=True)
        before = sorted(os.listdir(path.parent))
        self.assertIsNotNone(self.c.read_messages(path, NOW))
        self.assertEqual(sorted(os.listdir(path.parent)), before)

    def test_an_unreadable_messages_database_gives_none(self):
        path = self.root / "bad" / "messages.db"
        path.parent.mkdir()
        path.write_bytes(b"not a database" * 200)
        self.assertIsNone(self.c.read_messages(path, NOW))

    def test_a_missing_messages_database_gives_none_and_is_not_created(self):
        path = self.root / "empty" / "messages.db"
        path.parent.mkdir()
        self.assertIsNone(self.c.read_messages(path, NOW))
        self.assertFalse(path.exists())

    def _metrics_row(self, sid, used, cost=1.0, ts=NOW - 60, top_level=True):
        raw = {"session_id": sid, "model": {"id": "claude-x"}, "effort": {"level": "high"},
               "context_window": {"used_percentage": used, "context_window_size": 1000000},
               "cost": {"total_cost_usd": cost},
               "prompt_cache": {"warm": True, "expires_at": NOW + 1200, "hit_ratio": 0.93}}
        row = {"ts": iso(ts), "cwd": "/t/repo-tessa", "raw": raw}
        if top_level:
            row["session_id"] = sid
        return row

    def test_read_metrics_gives_the_last_record_of_the_session(self):
        path = self.root / "repo-tessa.jsonl"
        write_jsonl(path, [self._metrics_row("s1", 30.0, ts=NOW - 600),
                           self._metrics_row("s1", 42.5, cost=3.25, ts=NOW - 60)])
        got = self.c.read_metrics(path, "s1")
        self.assertEqual(got["used_pct"], 42.5)
        self.assertEqual(got["window"], 1000000)
        self.assertEqual(got["cost_usd"], 3.25)
        self.assertTrue(got["cache_warm"])
        self.assertEqual(got["cache_expires_at"], NOW + 1200)
        self.assertEqual(got["hit_ratio"], 0.93)
        self.assertEqual(got["model"], "claude-x")
        self.assertEqual(got["effort"], "high")
        self.assertIn("ts", got)

    def test_read_metrics_ignores_a_later_record_of_another_session(self):
        path = self.root / "repo-tessa.jsonl"
        write_jsonl(path, [self._metrics_row("s1", 42.5), self._metrics_row("s2", 99.0)])
        self.assertEqual(self.c.read_metrics(path, "s1")["used_pct"], 42.5)
        self.assertEqual(self.c.read_metrics(path, "s2")["used_pct"], 99.0)

    def test_read_metrics_also_matches_the_session_id_inside_raw(self):
        path = self.root / "repo-tessa.jsonl"
        write_jsonl(path, [self._metrics_row("s3", 12.0, top_level=False)])
        self.assertEqual(self.c.read_metrics(path, "s3")["used_pct"], 12.0)

    def test_read_metrics_is_none_when_the_session_has_no_record(self):
        path = self.root / "repo-tessa.jsonl"
        write_jsonl(path, [self._metrics_row("s1", 42.5)])
        self.assertIsNone(self.c.read_metrics(path, "zz"))
        self.assertIsNone(self.c.read_metrics(self.root / "missing.jsonl", "s1"))

    def test_count_compactions_counts_the_boundaries_of_a_small_transcript(self):
        path = self.root / "small.jsonl"
        boundary = {"type": "system", "subtype": "compact_boundary"}
        write_jsonl(path, [boundary, {"type": "user", "message": {"content": "hi"}}, boundary])
        count, partial = self.c.count_compactions(path)
        self.assertEqual(count, 2)
        self.assertFalse(partial)

    def test_count_compactions_reads_only_the_tail_of_a_large_transcript(self):
        path = self.root / "big.jsonl"
        boundary = {"type": "system", "subtype": "compact_boundary"}
        filler = {"type": "user", "message": {"content": "x" * 200}}
        write_jsonl(path, [boundary] + [filler] * 1500 + [boundary])
        count, partial = self.c.count_compactions(path)
        self.assertEqual(count, 1)       # the boundary at the top is past the last 64 KB
        self.assertTrue(partial)

    def _tool(self, name, tool_input=None):
        return {"type": "assistant",
                "message": {"content": [{"type": "tool_use", "name": name, "input": tool_input or {}}]}}

    def test_recent_tools_are_the_last_n_tool_uses(self):
        rows = [self._tool(f"t{i}") for i in range(7)] + [{"type": "user", "message": {"content": "ok"}}]
        names = [t["name"] for t in self.c.recent_tools(rows, n=5)]
        self.assertEqual(len(names), 5)
        self.assertEqual(sorted(names), ["t2", "t3", "t4", "t5", "t6"])

    def test_recent_tools_matches_full_walk_for_seeded_records_and_limits(self):
        rng = random.Random(7129)
        keys = ("command", "file_path", "description", "pattern")
        for _ in range(100):
            records = []
            for i in range(rng.randrange(30)):
                blocks = []
                for j in range(rng.randrange(6)):
                    given = {key: rng.choice(("", f"{key}-{i}-{j}" * 8, 42))
                             for key in keys if rng.choice((True, False))}
                    blocks.append(rng.choice((None, "not a block", {"type": "text"},
                                              {"type": "tool_use", "name": f"t{i}-{j}", "input": given},
                                              {"type": "tool_use", "name": f"empty{i}-{j}"})))
                content = rng.choice((blocks, blocks, "not a list", None))
                records.append({"type": rng.choice(("assistant", "assistant", "user", "system")),
                                "message": {"content": content}})
            calls = []
            for rec in records:
                content = rec["message"]["content"]
                for block in content if rec["type"] == "assistant" and isinstance(content, list) else ():
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        given = block.get("input") or {}
                        calls.append({"name": block.get("name"), "summary": next(
                            (str(given[k])[:60] for k in keys if given.get(k)), "")})
            for n in (-3, -1, 0, 1, 2, 5, 12, 50):
                with self.subTest(n=n):
                    self.assertEqual(self.c.recent_tools(records, n), calls[-n:])

    def test_recent_tools_stops_before_older_records_and_blocks(self):
        # A full walk reaches these sentinels even if it slices the same last two calls afterward.
        class Unvisited(dict):
            def get(self, key, default=None):
                raise AssertionError(f"visited older item: {key}")

        expected = [{"name": "Read", "summary": "/tmp/a"}, {"name": "Bash", "summary": "pwd"}]
        records = [Unvisited(type="assistant"), self._tool("Read", {"file_path": "/tmp/a"}),
                   self._tool("Bash", {"command": "pwd"})]
        with self.subTest(boundary="record"):
            self.assertEqual(self.c.recent_tools(records, 2), expected)

        records = [{"type": "assistant", "message": {"content": [
            Unvisited(type="tool_use"),
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/tmp/a"}},
            {"type": "tool_use", "name": "Bash", "input": {"command": "pwd"}},
        ]}}]
        with self.subTest(boundary="block"):
            self.assertEqual(self.c.recent_tools(records, 2), expected)

    def test_recent_tools_summary_is_the_first_60_characters_of_its_input(self):
        rows = [self._tool("Bash", {"command": "c" * 100}), self._tool("Read", {"file_path": "/a/b.py"}),
                self._tool("Glob", {})]
        by = {t["name"]: t["summary"] for t in self.c.recent_tools(rows, n=5)}
        self.assertEqual(by["Bash"], "c" * 60)
        self.assertEqual(by["Read"], "/a/b.py")
        self.assertEqual(by["Glob"], "")

    def _subagents(self):
        sdir = self.root / "sid-1"
        sub = sdir / "subagents"
        sub.mkdir(parents=True)
        user = {"type": "user", "timestamp": iso(NOW - 900), "message": {"content": "work"}}
        tool = {"type": "assistant", "message": {
            "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}],
            "usage": {"input_tokens": 10, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 5,
                      "output_tokens": 7}}}
        text = {"type": "assistant", "message": {"content": [{"type": "text", "text": "all green"}]}}

        def agent(name, meta, rows, mtime):
            (sub / f"agent-{name}.meta.json").write_text(json.dumps(meta))
            path = sub / f"agent-{name}.jsonl"
            write_jsonl(path, rows)
            os.utime(path, (mtime, mtime))

        agent("a1", {"agentType": "coder", "description": "port the parser", "spawnDepth": 2,
                     "parentAgentId": None, "finished": False, "inheritedWorktreePath": "/t/wt-a"},
              [user, tool], NOW - 30)
        agent("b2", {"agentType": "test-runner", "description": "run the tests", "parentAgentId": "a1",
                     "finished": False}, [user, text], NOW - 40)
        agent("c3", {"agentType": "reviewer", "description": "review", "spawnDepth": 1, "parentAgentId": None,
                     "finished": True}, [text], NOW - 100)
        agent("d4", {"agentType": "reviewer", "description": "old", "finished": True}, [text], NOW - 30000)
        agent("e5", {"agentType": "coder", "description": "stale", "finished": False}, [user], NOW - 30000)
        return sdir

    def test_read_subagents_lists_running_agents_and_recently_finished_ones(self):
        ids = {a["id"] for a in self.c.read_subagents(self._subagents(), NOW)}
        self.assertEqual(ids, {"a1", "b2", "c3"})

    def test_read_subagents_gives_a_running_agents_fields(self):
        a1 = next(a for a in self.c.read_subagents(self._subagents(), NOW) if a["id"] == "a1")
        self.assertEqual(a1["type"], "coder")
        self.assertEqual(a1["description"], "port the parser")
        self.assertEqual(a1["depth"], 2)
        self.assertIsNone(a1["parent"])
        self.assertFalse(a1["finished"])
        self.assertEqual(a1["worktree"], "/t/wt-a")
        self.assertEqual(a1["last_write"], NOW - 30)
        self.assertEqual(a1["last_state"], "in-turn")
        self.assertEqual(a1["tokens"], 122)

    def test_read_subagents_reads_an_ended_turn_and_defaults_depth_and_parent(self):
        b2 = next(a for a in self.c.read_subagents(self._subagents(), NOW) if a["id"] == "b2")
        self.assertEqual(b2["last_state"], "ended")
        self.assertEqual(b2["depth"], 1)
        self.assertEqual(b2["parent"], "a1")
        self.assertIsNone(b2["worktree"])

    def test_read_subagents_gives_a_finished_agent_its_write_time(self):
        c3 = next(a for a in self.c.read_subagents(self._subagents(), NOW) if a["id"] == "c3")
        self.assertTrue(c3["finished"])
        self.assertEqual(c3["last_write"], NOW - 100)

    def test_git_dir_is_the_dot_git_folder(self):
        wt = self.root / "wt"
        (wt / ".git").mkdir(parents=True)
        self.assertEqual(Path(self.c.git_dir(wt)), wt / ".git")

    def test_git_dir_follows_a_dot_git_file(self):
        wt = self.root / "wt2"
        wt.mkdir()
        real = self.root / "main" / ".git" / "worktrees" / "wt2"
        (wt / ".git").write_text(f"gitdir: {real}\n")
        # git_dir resolves symlinks (macOS temp folders live under /private/var): compare resolved paths
        self.assertEqual(Path(self.c.git_dir(wt)).resolve(), real.resolve())

    def test_git_dir_is_none_without_git(self):
        self.assertIsNone(self.c.git_dir(self.root / "plain"))

    def _holder_file(self, name="codeteam-warm.lock", pid=4242, since=NOW - 90):
        path = self.root / name
        path.write_text(json.dumps({"pid": pid, "team": "tessa", "session": "Coord-a", "worktree": "/t/wt",
                                    "tool": "cargo", "since": int(since)}))
        return path

    def test_read_holder_of_a_live_pid_is_held_with_its_fields(self):
        got = self.c.read_holder(self._holder_file(), {4242})
        self.assertEqual(got["state"], "held")
        self.assertEqual(got["pid"], 4242)
        self.assertEqual(got["team"], "tessa")
        self.assertEqual(got["session"], "Coord-a")
        self.assertEqual(got["worktree"], "/t/wt")
        self.assertEqual(got["tool"], "cargo")
        self.assertEqual(got["since"], int(NOW - 90))

    def test_read_holder_of_a_dead_pid_is_free(self):
        self.assertEqual(self.c.read_holder(self._holder_file(), set())["state"], "free")

    def test_read_holder_is_question_mark_when_empty_old_format_or_unreadable(self):
        empty = self.root / "empty"
        empty.write_text("")
        old = self.root / "old"
        old.write_text("4242 cargo build\n")
        unreadable = self.root / "unreadable"
        unreadable.mkdir()
        for path in (empty, old, unreadable):
            with self.subTest(path=path.name):
                self.assertEqual(self.c.read_holder(path, {4242})["state"], "?")

    def test_reading_a_holder_leaves_its_bytes_and_mtime_alone(self):
        path = self._holder_file()
        os.utime(path, (NOW - 90, NOW - 90))
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        self.c.read_holder(path, {4242})
        self.c.read_holder(path, set())
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def _worktree(self):
        wt = self.root / "wt"
        (wt / ".git").mkdir(parents=True, exist_ok=True)
        return wt

    def _warm_lock(self, wt, text, mtime=None):
        path = wt / ".git" / "codeteam-warm.lock"
        path.write_text(text)
        if mtime is not None:
            os.utime(path, (mtime, mtime))

    def test_read_warm_is_none_without_a_lock(self):
        self.assertIsNone(self.c.read_warm(self._worktree(), {777}, NOW))

    def test_read_warm_with_a_live_holder_is_held_with_elapsed_time(self):
        wt = self._worktree()
        self._warm_lock(wt, json.dumps({"pid": 777, "team": "tessa", "session": None, "worktree": str(wt),
                                        "tool": "warm", "since": int(NOW - 100)}))
        got = self.c.read_warm(wt, {777}, NOW)
        self.assertEqual(got["state"], "held")
        self.assertEqual(got["elapsed_s"], 100)

    def test_read_warm_with_a_dead_holder_is_none(self):
        wt = self._worktree()
        self._warm_lock(wt, json.dumps({"pid": 777, "team": "tessa", "session": None, "worktree": str(wt),
                                        "tool": "warm", "since": int(NOW - 100)}))
        self.assertIsNone(self.c.read_warm(wt, set(), NOW))

    def test_read_warm_empty_and_older_than_840_seconds_is_none(self):
        wt = self._worktree()
        self._warm_lock(wt, "", mtime=NOW - 900)
        self.assertIsNone(self.c.read_warm(wt, set(), NOW))

    def test_read_warm_empty_and_newer_than_840_seconds_is_question_mark(self):
        wt = self._worktree()
        self._warm_lock(wt, "", mtime=NOW - 60)
        self.assertEqual(self.c.read_warm(wt, set(), NOW)["state"], "?")


class QueueReadTests(unittest.TestCase):
    """read_job and read_queue over job files and a queue.toml written as fixtures. The deck only reads: a job file is
    never changed, and one it cannot read is counted as unknown, never raised."""

    def setUp(self):
        from codeteam2.deck import collect
        self.c = collect
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.queue = self.root / "run" / "queue"
        self.config = self.root / "run" / "queue.toml"
        self.queue.mkdir(parents=True)
        self.config.write_text(QUEUE_TOML)
        clear_queue_env(self)

    def read(self, alive=frozenset({111})):
        return self.c.read_queue(self.queue, self.config, alive, NOW)

    def test_read_job_gives_each_of_the_four_states(self):
        for state in ("queued", "running", "done", "broken"):
            with self.subTest(state=state):
                path = put_job(self.queue, "t1", job("t1", state=state))
                self.assertEqual(self.c.read_job(path)["state"], state)

    def test_read_job_gives_each_of_the_four_classes(self):
        for cls in ("full", "post", "pre", "dev"):
            with self.subTest(cls=cls):
                path = put_job(self.queue, "t1", job("t1", cls=cls))
                self.assertEqual(self.c.read_job(path)["class"], cls)

    def test_read_job_keeps_the_listed_fields_and_never_env_or_command(self):
        path = put_job(self.queue, "t1", job(
            "t1", cls="post", state="running", kind="run", key="k1", worktree="/t/wt", team="tessa", session="Coord-a",
            submitted=NOW - 300, started=NOW - 60, pid=111, cost=2.5, estimated_start=None,
            env={"ZONE_TOKEN": "env-marker-4417"}, command="make zone-test-one DIR=cmd-marker-9021",
            zone_extra="not listed"))
        got = self.c.read_job(path)
        self.assertEqual(
            {k: got[k] for k in ("ticket", "class", "key", "worktree", "team", "session", "submitted", "started",
                                 "pid", "state", "cost")},
            {"ticket": "t1", "class": "post", "key": "k1", "worktree": "/t/wt", "team": "tessa", "session": "Coord-a",
             "submitted": NOW - 300, "started": NOW - 60, "pid": 111, "state": "running", "cost": 2.5})
        self.assertEqual(got.get("kind"), "run")
        for absent in ("env", "command", "zone_extra"):
            self.assertNotIn(absent, got)
        self.assertNotIn("env-marker-4417", json.dumps(got))
        self.assertNotIn("cmd-marker-9021", json.dumps(got))

    def test_read_job_is_none_for_a_file_of_unknown_shape_or_unreadable_bytes(self):
        texts = {"state.json": json.dumps(job("t1", state="stuck")).encode(),
                 "class.json": json.dumps(job("t1", cls="gold")).encode(),
                 "list.json": b"[1, 2]",
                 "empty.json": b"",
                 "half.json": b'{"ticket": "t1", "sta',
                 "latin.json": b"\xff\xfe\x00{"}
        for name, data in texts.items():
            with self.subTest(name=name):
                path = self.queue / name
                path.write_bytes(data)
                self.assertIsNone(self.c.read_job(path))
        with self.subTest(name="x.json"):
            (self.queue / "x.json").mkdir()
            self.assertIsNone(self.c.read_job(self.queue / "x.json"))

    def test_read_job_turns_a_non_numeric_time_or_cost_and_a_bool_or_string_pid_into_none(self):
        for field, value in (("started", "soon"), ("submitted", True), ("cost", "2.5"), ("estimated_start", False),
                             ("pid", True), ("pid", "4242")):
            with self.subTest(field=field, value=value):
                path = put_job(self.queue, "t1", job("t1", state="running", **{field: value}))
                self.assertIsNone(self.c.read_job(path)[field])

    def test_read_job_copies_position_hold_and_kind_and_gives_none_for_a_value_of_the_wrong_type(self):
        got = self.c.read_job(put_job(self.queue, "t1", job("t1", position=2, hold="warm", kind="slot")))
        self.assertEqual((got.get("position"), got.get("hold"), got.get("kind")), (2, "warm", "slot"))
        for field, value in (("position", True), ("position", "2"), ("position", 1.5), ("hold", True),
                             ("hold", ["warm"]), ("kind", 5)):
            with self.subTest(field=field, value=value):
                got = self.c.read_job(put_job(self.queue, "t1", job("t1", **{field: value})))
                self.assertIsNone(got.get(field))

    def test_read_job_takes_the_ticket_from_the_file_name_when_the_file_has_none_or_a_non_text_one(self):
        path = self.queue / "t7.json"
        for row in ({"class": "full", "state": "queued"}, {"ticket": 5, "class": "full", "state": "queued"}):
            with self.subTest(row=row):
                path.write_text(json.dumps(row))
                self.assertEqual(self.c.read_job(path)["ticket"], "t7")

    def test_queued_jobs_are_ordered_by_the_position_the_file_gives_and_it_is_passed_through(self):
        put_job(self.queue, "t-late", job("t-late", submitted=NOW - 10, position=1))
        put_job(self.queue, "t-early", job("t-early", submitted=NOW - 300, position=5))
        queued = queue_class(self.read(), "full")["queued"]
        self.assertEqual(tickets(queued), ["t-late", "t-early"])
        self.assertEqual([q["position"] for q in queued], [1, 5])
        self.assertEqual([q["waiting_s"] for q in queued], [10, 300])

    def test_no_position_goes_after_the_positioned_then_submit_time_then_ticket(self):
        put_job(self.queue, "p2", job("p2", submitted=None, position=2))
        put_job(self.queue, "p1", job("p1", submitted=NOW - 10, position=1))
        put_job(self.queue, "n-b", job("n-b", submitted=NOW - 50))
        put_job(self.queue, "n-a", job("n-a", submitted=NOW - 50))
        put_job(self.queue, "n-z", job("n-z", submitted=None))
        queued = queue_class(self.read(), "full")["queued"]
        self.assertEqual(tickets(queued), ["p1", "p2", "n-a", "n-b", "n-z"])
        self.assertEqual([q["position"] for q in queued], [1, 2, None, None, None])
        self.assertIsNone(queued[4]["waiting_s"])

    def test_running_jobs_give_how_long_they_have_run_oldest_start_first(self):
        put_job(self.queue, "r-new", job("r-new", state="running", started=NOW - 60, pid=111))
        put_job(self.queue, "r-old", job("r-old", state="running", started=NOW - 600, pid=111))
        put_job(self.queue, "r-none", job("r-none", state="running", pid=111))
        running = queue_class(self.read(), "full")["running"]
        self.assertEqual(tickets(running), ["r-old", "r-new", "r-none"])
        self.assertEqual([r["running_s"] for r in running], [600, 60, None])

    def test_a_running_job_whose_pid_is_not_alive_is_flagged_and_its_file_is_left_alone(self):
        dead = put_job(self.queue, "r-dead", job("r-dead", state="running", started=NOW - 60, pid=4242))
        put_job(self.queue, "r-live", job("r-live", state="running", started=NOW - 30, pid=111))
        os.utime(dead, (NOW - 900, NOW - 900))
        before = (dead.read_bytes(), dead.stat().st_mtime_ns)
        running = {r["ticket"]: r for r in queue_class(self.read(alive={111}), "full")["running"]}
        self.assertIs(running["r-dead"]["pid_alive"], False)
        self.assertIs(running["r-live"]["pid_alive"], True)
        self.assertEqual((dead.read_bytes(), dead.stat().st_mtime_ns), before)

    def test_a_running_job_with_no_pid_is_not_alive(self):
        put_job(self.queue, "r1", job("r1", state="running", started=NOW - 60))
        self.assertIs(queue_class(self.read(), "full")["running"][0]["pid_alive"], False)

    def test_pid_alive_is_none_when_the_process_list_is_unknown(self):
        put_job(self.queue, "r1", job("r1", state="running", started=NOW - 60, pid=111))
        self.assertIsNone(queue_class(self.read(alive=None), "full")["running"][0]["pid_alive"])

    def test_estimated_start_is_shown_as_the_file_says_null_or_set(self):
        put_job(self.queue, "q-null", job("q-null", submitted=NOW - 60, estimated_start=None))
        put_job(self.queue, "q-set", job("q-set", submitted=NOW - 30, estimated_start=NOW + 300))
        queued = {q["ticket"]: q for q in queue_class(self.read(), "full")["queued"]}
        self.assertIsNone(queued["q-null"]["estimated_start"])
        self.assertEqual(queued["q-set"]["estimated_start"], NOW + 300)

    def test_the_classes_come_in_full_post_pre_dev_order_whatever_the_files_say(self):
        put_job(self.queue, "d1", job("d1", cls="dev", submitted=NOW - 10))
        put_job(self.queue, "p1", job("p1", cls="pre", submitted=NOW - 10))
        got = self.read()
        self.assertEqual([c["class"] for c in got["classes"]], ["full", "post", "pre", "dev"])
        self.assertEqual(tickets(queue_class(got, "dev")["queued"]), ["d1"])

    def test_each_class_takes_its_guaranteed_and_ceiling_from_queue_toml_and_a_dev_ceiling_of_zero_is_kept(self):
        self.assertEqual([(c.get("guaranteed"), c.get("ceiling")) for c in self.read()["classes"]],
                         [(1, 1), (1, 2), (1, 2), (1, 0)])

    def test_unreadable_empty_and_half_written_files_count_as_unknown_and_temporary_lock_and_log_names_are_skipped(self):
        put_job(self.queue, "t1", job("t1", submitted=NOW - 60))
        put_job(self.queue, ".t9", job("t9", submitted=NOW - 60))      # a dotfile: skipped, not counted
        (self.queue / ".t8.json.tmp").write_text("{")                  # the runner's temporary file: ignored
        (self.queue / "t5.json.tmp").write_text("{")                   # a *.tmp name: ignored
        (self.queue / ".lock").write_text("")
        (self.queue / ".runner.lock").write_text("")
        (self.queue / "x.log").write_text("a run job's output")         # not *.json: ignored
        (self.queue / "empty.json").write_text("")
        (self.queue / "half.json").write_text('{"ticket": "t2", "sta')
        (self.queue / "latin.json").write_bytes(b"\xff\xfe\x00")
        (self.queue / "list.json").write_text("[1, 2]")
        (self.queue / "stuck.json").write_text(json.dumps(job("t3", state="stuck")))
        (self.queue / "x.json").mkdir()
        got = self.read()
        self.assertEqual(got["unknown"], 6)
        self.assertEqual(tickets(queue_class(got, "full")["queued"]), ["t1"])

    def test_a_job_file_nested_too_deep_to_parse_is_unknown_and_never_raises(self):
        (self.queue / "x.json").write_text("[" * 200000)
        self.assertIsNone(self.c.read_job(self.queue / "x.json"))
        self.assertEqual(self.read()["unknown"], 1)

    def test_waits_count_only_jobs_started_in_the_last_24_hours(self):
        put_job(self.queue, "d1", job("d1", state="done", submitted=NOW - 1000, started=NOW - 700,
                                      finished=NOW - 650))
        put_job(self.queue, "d2", job("d2", state="done", submitted=NOW - 2000, started=NOW - 1100,
                                      finished=NOW - 1000))
        put_job(self.queue, "d-old", job("d-old", state="done", submitted=NOW - 25 * HOUR - 600,
                                         started=NOW - 25 * HOUR, finished=NOW - 25 * HOUR + 60))
        full = queue_class(self.read(), "full")
        self.assertEqual(full["waits"], {"n": 2, "median_s": 600, "max_s": 900, "window_h": 24})
        self.assertEqual((full["running"], full["queued"]), ([], []))

    def test_waits_are_kept_per_class(self):
        put_job(self.queue, "p1", job("p1", cls="post", state="done", submitted=NOW - 160, started=NOW - 100))
        got = self.read()
        self.assertEqual(queue_class(got, "post")["waits"], {"n": 1, "median_s": 60, "max_s": 60, "window_h": 24})
        self.assertEqual(queue_class(got, "full")["waits"]["n"], 0)

    def test_a_class_with_no_waits_has_no_median_or_max(self):
        self.assertEqual(queue_class(self.read(), "dev")["waits"],
                         {"n": 0, "median_s": None, "max_s": None, "window_h": 24})

    def test_a_running_job_counts_its_wait_once_it_has_started(self):
        put_job(self.queue, "r1", job("r1", state="running", submitted=NOW - 400, started=NOW - 100, pid=111))
        self.assertEqual(queue_class(self.read(), "full")["waits"]["median_s"], 300)

    def test_broken_counts_the_broken_jobs_finished_inside_the_window(self):
        put_job(self.queue, "b1", job("b1", state="broken", finished=NOW - 600))
        put_job(self.queue, "b2", job("b2", state="broken", finished=NOW - 25 * HOUR))
        self.assertEqual(queue_class(self.read(), "full")["broken"], 1)

    def test_a_shorter_retention_narrows_the_waits_and_broken_window_and_says_so(self):
        self.config.write_text("retention_hours = 6\n")
        put_job(self.queue, "d-in", job("d-in", state="done", submitted=NOW - 2 * HOUR - 300,
                                        started=NOW - 2 * HOUR, finished=NOW - 2 * HOUR + 60))
        put_job(self.queue, "d-out", job("d-out", state="done", submitted=NOW - 10 * HOUR - 100,
                                         started=NOW - 10 * HOUR, finished=NOW - 10 * HOUR + 60))
        put_job(self.queue, "b-in", job("b-in", state="broken", finished=NOW - 5 * HOUR))
        put_job(self.queue, "b-out", job("b-out", state="broken", finished=NOW - 7 * HOUR))
        full = queue_class(self.read(), "full")
        self.assertEqual(full["waits"], {"n": 1, "median_s": 300, "max_s": 300, "window_h": 6})
        self.assertEqual(full["broken"], 1)

    def test_held_counts_the_queued_jobs_of_each_class_by_their_hold(self):
        put_job(self.queue, "q1", job("q1", submitted=NOW - 50, position=1, hold="warm"))
        put_job(self.queue, "q2", job("q2", submitted=NOW - 40, position=2, hold="warm"))
        put_job(self.queue, "q3", job("q3", submitted=NOW - 30, position=3, hold="load"))
        put_job(self.queue, "q4", job("q4", submitted=NOW - 20, position=4, hold="swap"))
        put_job(self.queue, "q5", job("q5", submitted=NOW - 10, position=5, hold=None))
        put_job(self.queue, "p1", job("p1", cls="post", submitted=NOW - 10, position=1))
        got = self.read()
        self.assertEqual(queue_class(got, "full")["held"], {"warm": 2, "load": 1, "swap": 1})
        self.assertEqual(queue_class(got, "post")["held"], {"warm": 0, "load": 0, "swap": 0})

    def test_the_queue_carries_the_runner_state_from_the_runner_file_and_no_budget_in_use_or_guard_of_its_own(self):
        write_runner(self.queue.parent / "queue-runner.json", budget=8, used=4.0)
        got = self.read()
        self.assertEqual(set(got), {"state", "unknown", "runner", "classes"})
        self.assertEqual((got["runner"]["state"], got["runner"]["budget"], got["runner"]["used"]), ("live", 8, 4.0))

    def test_with_no_runner_file_the_runner_is_none_and_queue_toml_gives_no_budget_for_it(self):
        self.assertEqual(self.read()["runner"], {**{k: None for k in RUNNER_KEYS}, "state": "none"})

    def test_an_existing_queue_folder_is_state_ok(self):
        self.assertEqual(self.read()["state"], "ok")

    def test_a_missing_queue_folder_is_state_question_mark_with_four_empty_classes(self):
        got = self.c.read_queue(self.root / "nope", self.config, set(), NOW)
        self.assertEqual(got["state"], "?")
        self.assertEqual([(c["class"], c["running"], c["queued"]) for c in got["classes"]],
                         [("full", [], []), ("post", [], []), ("pre", [], []), ("dev", [], [])])


class QueueConfigTests(unittest.TestCase):
    """read_queue_config mirrors the runner's load_config, key by key, with zone's defaults: a missing, malformed,
    partial or wrong-typed queue.toml gives the default for what it does not say, and nothing raises."""

    def setUp(self):
        from codeteam2.deck import collect
        self.c = collect
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "queue.toml"
        clear_queue_env(self)

    def config(self, text):
        self.path.write_text(text)
        return self.c.read_queue_config(self.path)

    def test_the_layout_is_read_as_interface_gives_it(self):
        self.assertEqual(self.config(QUEUE_TOML), {
            "retention_hours": 24,
            "classes": {"full": {"guaranteed": 1, "ceiling": 1}, "post": {"guaranteed": 1, "ceiling": 2},
                        "pre": {"guaranteed": 1, "ceiling": 2}, "dev": {"guaranteed": 1, "ceiling": 0}}})

    def test_a_missing_queue_toml_gives_zone_defaults_key_by_key(self):
        self.assertEqual(self.c.read_queue_config(self.path), ZONE_DEFAULTS)

    def test_a_malformed_queue_toml_gives_zone_defaults(self):
        self.assertEqual(self.config("retention_hours = [\n[classes\n"), ZONE_DEFAULTS)

    def test_an_unreadable_queue_toml_gives_zone_defaults(self):
        self.path.mkdir()
        self.assertEqual(self.c.read_queue_config(self.path), ZONE_DEFAULTS)
        self.path.rmdir()
        self.path.write_bytes(b"\xff\xfe\x00")
        self.assertEqual(self.c.read_queue_config(self.path), ZONE_DEFAULTS)

    def test_only_retention_and_the_class_limits_are_kept_and_top_level_budget_load_and_swap_are_not_read(self):
        cfg = self.config("budget = 99\nload_max = 3\nswap_max = 0.5\nslot_cost = 4\n")
        self.assertEqual(set(cfg), {"retention_hours", "classes"})
        self.assertEqual(cfg, ZONE_DEFAULTS)

    def test_a_partial_queue_toml_gives_what_it_says_and_zone_defaults_for_the_rest(self):
        self.assertEqual(self.config("retention_hours = 6\n[classes.pre]\nguaranteed = 2\n"), {
            "retention_hours": 6,
            "classes": {"full": {"guaranteed": 1, "ceiling": 1}, "post": {"guaranteed": 1, "ceiling": 2},
                        "pre": {"guaranteed": 2, "ceiling": 2}, "dev": {"guaranteed": 1, "ceiling": 0}}})

    def test_a_wrong_typed_value_gives_its_default_key_by_key(self):
        self.assertEqual(self.config('retention_hours = "soon"\n[classes.full]\nguaranteed = "one"\n'
                                     '[classes.post]\nceiling = [2]\n[classes.dev]\nceiling = "many"\n'),
                         ZONE_DEFAULTS)

    def test_a_numeric_string_is_read_as_the_runner_reads_it(self):
        cfg = self.config('retention_hours = "6"\n[classes.pre]\nguaranteed = "2"\n')
        self.assertEqual((cfg["retention_hours"], cfg["classes"]["pre"]["guaranteed"]), (6.0, 2))

    def test_true_is_read_as_one_as_the_runner_reads_it(self):
        self.assertEqual(self.config("retention_hours = true\n")["retention_hours"], 1.0)

    def test_a_whole_number_too_big_for_a_float_gives_its_default(self):
        big = "1" + "0" * 400
        cfg = self.config(f"retention_hours = {big}\n[classes.post]\nceiling = {big}\n")
        self.assertEqual((cfg["retention_hours"], cfg["classes"]["post"]["ceiling"]), (24, 2))

    def test_a_nan_or_infinite_value_gives_its_default(self):
        cfg = self.config("retention_hours = inf\n[classes.full]\nceiling = nan\n[classes.pre]\nguaranteed = -inf\n")
        self.assertEqual(cfg, ZONE_DEFAULTS)

    def test_non_table_classes_gives_the_class_defaults_and_keeps_the_retention(self):
        self.assertEqual(self.config("retention_hours = 6\nclasses = 3\n"),
                         {"retention_hours": 6, "classes": ZONE_DEFAULTS["classes"]})

    def test_a_non_table_class_entry_gives_that_class_its_defaults(self):
        cfg = self.config('[classes]\nfull = 3\npost = "x"\n[classes.pre]\nguaranteed = 2\n')
        self.assertEqual(cfg["classes"], {"full": {"guaranteed": 1, "ceiling": 1},
                                          "post": {"guaranteed": 1, "ceiling": 2},
                                          "pre": {"guaranteed": 2, "ceiling": 2},
                                          "dev": {"guaranteed": 1, "ceiling": 0}})


class QueueRunnerTests(unittest.TestCase):
    """read_runner over queue-runner.json: live, stale or none, and the files that read as "?". The deck only reads
    the runner's state: no byte, mtime or folder entry changes, and no lock is taken or created."""

    def setUp(self):
        from codeteam2.deck import collect
        self.c = collect
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run = Path(tmp.name) / "run"
        self.run.mkdir()
        self.path = self.run / "queue-runner.json"
        clear_queue_env(self)

    def read(self, alive=frozenset({111}), now=NOW):
        return self.c.read_runner(self.path, alive, now)

    def assert_gives_no_numbers(self, got, beat_age_s):
        """Every number and hold is None (the deck invents nothing); beat_age_s is what the beat gives."""
        self.assertEqual({k: v for k, v in got.items() if k not in ("state", "pid")},
                         {**{k: None for k in RUNNER_KEYS - {"state", "pid"}}, "beat_age_s": beat_age_s})

    def test_a_fresh_beat_from_a_live_pid_is_live_and_gives_its_pid_numbers_and_holds(self):
        write_runner(self.path)
        self.assertEqual(self.read(), {"state": "live", "pid": 111, "beat_age_s": 5, "budget": 6, "used": 1.5,
                                       "load": 2.0, "load_max": 36, "swap": 0.1, "swap_max": 0.9,
                                       "load_hold": False, "swap_hold": False})

    def test_a_beat_of_exactly_60_seconds_is_live_and_an_older_beat_is_stale(self):
        write_runner(self.path, beat=NOW - 60)
        self.assertEqual(self.read()["state"], "live")
        write_runner(self.path, beat=NOW - 61)
        self.assertEqual(self.read()["state"], "stale")

    def test_codeteam_buildq_stale_sets_the_age_a_beat_may_reach(self):
        write_runner(self.path, beat=NOW - 15)
        self.assertEqual(self.read()["state"], "live")
        with patch.dict(os.environ, {"CODETEAM_BUILDQ_STALE": "10"}):
            self.assertEqual(self.read()["state"], "stale")

    def test_a_pid_not_in_alive_pids_is_stale_even_with_a_fresh_beat(self):
        write_runner(self.path)
        self.assert_gives_no_numbers(self.read(alive={222}), beat_age_s=5)
        self.assertEqual(self.read(alive={222})["state"], "stale")

    def test_alive_pids_none_skips_the_pid_test(self):
        write_runner(self.path, pid=4242)
        self.assertEqual(self.read(alive=None)["state"], "live")

    def test_a_stale_beat_gives_no_numbers_or_holds_but_the_beat_age(self):
        write_runner(self.path, beat=NOW - 61)
        got = self.read()
        self.assertEqual(got["state"], "stale")
        self.assert_gives_no_numbers(got, beat_age_s=61)

    def test_no_runner_file_is_none_with_nothing_else(self):
        self.assertEqual(self.read(), {**{k: None for k in RUNNER_KEYS}, "state": "none"})

    def test_an_empty_half_written_list_or_string_beat_runner_file_is_question_mark(self):
        for text in ("", '{"pid": 111, "beat": ', "[1, 2]", json.dumps({**RUNNER_FIELDS, "beat": "soon"})):
            self.path.write_text(text)
            got = self.read()
            self.assertEqual(got["state"], "?", text)
            self.assert_gives_no_numbers(got, beat_age_s=None)

    def test_a_runner_file_that_cannot_be_read_is_question_mark(self):
        self.path.mkdir()
        self.assertEqual(self.read()["state"], "?")

    def test_a_beat_that_is_nan_or_infinite_is_question_mark(self):
        for beat in (float("nan"), float("inf")):
            write_runner(self.path, beat=beat)
            self.assertEqual(self.read()["state"], "?", beat)

    def test_nan_and_infinite_numbers_read_as_none_and_the_rest_is_kept(self):
        write_runner(self.path, budget=float("nan"), used=float("inf"), swap=float("-inf"))
        got = self.read()
        self.assertEqual((got["state"], got["budget"], got["used"], got["swap"]), ("live", None, None, None))
        self.assertEqual((got["load"], got["load_max"], got["swap_max"]), (2.0, 36, 0.9))

    def test_a_hold_that_is_not_a_bool_reads_as_none_and_a_bool_is_kept(self):
        write_runner(self.path, load_hold="yes", swap_hold=1)
        got = self.read()
        self.assertEqual((got["load_hold"], got["swap_hold"]), (None, None))
        write_runner(self.path, load_hold=True, swap_hold=False)
        got = self.read()
        self.assertIs(got["load_hold"], True)
        self.assertIs(got["swap_hold"], False)

    def test_reading_the_runner_changes_no_byte_mtime_or_entry_under_run_and_creates_no_lock(self):
        write_runner(self.path)
        queue = self.run / "queue"
        queue.mkdir()
        (queue / ".runner.lock").write_text("")
        os.utime(self.path, (NOW - 900, NOW - 900))
        before = self.run_listing()
        self.read()
        self.read(alive=None)
        self.assertEqual(self.run_listing(), before)

    def run_listing(self):
        """Every path under run/ with its kind, bytes and mtime."""
        return {p: (p.is_dir(), p.read_bytes() if p.is_file() else None, p.stat().st_mtime_ns)
                for p in [self.run, *sorted(self.run.rglob("*"))]}


class QueueCollectTests(unittest.TestCase):
    """collect() over a fixture run/ folder: the snapshot's builds["queue"], the job fields that never reach the
    snapshot, CODETEAM_QUEUE_DIR, and the deck writing nothing under run/."""

    def setUp(self):
        from codeteam2.deck import collect
        self.c = collect
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.run = self.root / "run"
        self.queue = self.run / "queue"
        self.queue.mkdir(parents=True)
        (self.run / "queue.toml").write_text(QUEUE_TOML)
        self.teams = self.root / "teams"
        self.projects = self.root / "projects"
        self.metrics = self.root / "metrics"
        for d in (self.teams, self.projects, self.metrics):
            d.mkdir()
        self.herdr = ReadOnlyHerdr(agents=[], panes=[])
        clear_queue_env(self)

    def snapshot(self, now=NOW, cache=None):
        return self.c.collect(teams_dir=self.teams, now=now, herdr=self.herdr, ps_text=PS_RUNNER,
                              queue_dir=self.queue, metrics_dir=self.metrics, projects_dir=self.projects, cache=cache)

    def record_run(self):
        """Every path under run/ with its kind, bytes and mtime: a write, a new file or a moved mtime shows here."""
        return {p: (p.is_dir(), p.read_bytes() if p.is_file() else None, p.stat().st_mtime_ns)
                for p in [self.run, *sorted(self.run.rglob("*"))]}

    def test_collect_gives_the_queue_the_contract_shape(self):
        put_job(self.queue, "r1", job("r1", state="running", started=NOW - 60, pid=111, cost=2.5, team="tessa"))
        queue = self.snapshot()["builds"]["queue"]
        self.assertEqual(set(queue), {"state", "unknown", "runner", "classes"})
        self.assertEqual((queue["state"], queue["unknown"]), ("ok", 0))
        self.assertEqual(set(queue["runner"]), RUNNER_KEYS)
        self.assertEqual([c["class"] for c in queue["classes"]], ["full", "post", "pre", "dev"])
        for c in queue["classes"]:
            with self.subTest(cls=c["class"]):
                self.assertEqual(set(c), {"class", "guaranteed", "ceiling", "held", "running", "queued", "waits",
                                          "broken"})
                self.assertEqual(set(c["waits"]), {"n", "median_s", "max_s", "window_h"})
        running = queue_class(queue, "full")["running"][0]
        self.assertTrue({"running_s", "pid_alive", "ticket", "team", "cost"} <= set(running), running)

    def test_collect_gives_the_runner_its_numbers_and_the_budget_in_use_comes_from_it(self):
        write_runner(self.run / "queue-runner.json", budget=8, used=4.0)
        runner = self.snapshot()["builds"]["queue"]["runner"]
        self.assertEqual((runner["state"], runner["budget"], runner["used"]), ("live", 8, 4.0))

    def test_no_job_env_or_command_reaches_the_snapshot(self):
        put_job(self.queue, "r1", job("r1", state="running", started=NOW - 60, pid=111,
                                      env={"ZONE_TOKEN": "env-marker-4417"},
                                      command="make zone-test-one DIR=cmd-marker-9021"))
        snap = self.snapshot()
        self.assertEqual(tickets(queue_class(snap["builds"]["queue"], "full")["running"]), ["r1"])
        text = json.dumps(snap)
        self.assertNotIn("env-marker-4417", text)
        self.assertNotIn("cmd-marker-9021", text)

    def test_builds_carries_the_queue_dict_and_no_slots_key(self):
        builds = self.snapshot()["builds"]
        self.assertNotIn("slots", builds)
        self.assertIsInstance(builds["queue"], dict)

    def test_collect_reads_the_codeteam_queue_dir_when_no_queue_dir_is_given(self):
        put_job(self.queue, "env-job", job("env-job", state="running", started=NOW - 60, pid=111))
        with patch.dict(os.environ, {"CODETEAM_QUEUE_DIR": str(self.queue)}):
            snap = self.c.collect(teams_dir=self.teams, now=NOW, herdr=self.herdr, ps_text="",
                                  metrics_dir=self.metrics, projects_dir=self.projects)
        self.assertEqual(tickets(queue_class(snap["builds"]["queue"], "full")["running"]), ["env-job"])

    def test_an_empty_codeteam_queue_dir_means_unset_and_the_run_queue_is_read(self):
        put_job(self.queue, "run-job", job("run-job", state="running", started=NOW - 60, pid=111))
        with patch("codeteam2.deck.collect.CT_HOME", self.root), patch.dict(os.environ, {"CODETEAM_QUEUE_DIR": ""}):
            snap = self.c.collect(teams_dir=self.teams, now=NOW, herdr=self.herdr, ps_text=PS_RUNNER,
                                  metrics_dir=self.metrics, projects_dir=self.projects)
        self.assertEqual(tickets(queue_class(snap["builds"]["queue"], "full")["running"]), ["run-job"])

    def test_codeteam_queue_conf_points_the_config_elsewhere(self):
        elsewhere = self.root / "elsewhere.toml"
        elsewhere.write_text("[classes.full]\nguaranteed = 1\nceiling = 5\n")
        with patch.dict(os.environ, {"CODETEAM_QUEUE_CONF": str(elsewhere)}):
            queue = self.snapshot()["builds"]["queue"]
        self.assertEqual(queue_class(queue, "full")["ceiling"], 5)

    def test_an_explicit_queue_conf_beats_codeteam_queue_conf(self):
        explicit = self.root / "explicit.toml"
        explicit.write_text("[classes.full]\nceiling = 3\n")
        env_conf = self.root / "env.toml"
        env_conf.write_text("[classes.full]\nceiling = 5\n")
        with patch.dict(os.environ, {"CODETEAM_QUEUE_CONF": str(env_conf)}):
            snap = self.c.collect(teams_dir=self.teams, now=NOW, herdr=self.herdr, ps_text=PS_RUNNER,
                                  queue_dir=self.queue, queue_conf=explicit, metrics_dir=self.metrics,
                                  projects_dir=self.projects)
        self.assertEqual(queue_class(snap["builds"]["queue"], "full")["ceiling"], 3)

    def test_an_empty_codeteam_queue_conf_means_unset_and_the_queue_toml_beside_the_queue_is_read(self):
        (self.run / "queue.toml").write_text("[classes.full]\nguaranteed = 1\nceiling = 4\n")
        with patch.dict(os.environ, {"CODETEAM_QUEUE_CONF": ""}):
            queue = self.snapshot()["builds"]["queue"]
        self.assertEqual(queue_class(queue, "full")["ceiling"], 4)

    def test_collect_runs_no_sysctl(self):
        calls = []

        def refuse(argv, *args, **kwargs):
            calls.append(argv)
            raise FileNotFoundError(2, "not run in a test", argv[0])

        with patch("codeteam2.deck.collect.subprocess.run", side_effect=refuse):
            self.c.collect(teams_dir=self.teams, now=NOW, herdr=self.herdr, ps_text=PS_RUNNER,
                           queue_dir=self.queue, metrics_dir=self.metrics, projects_dir=self.projects)
        self.assertEqual([argv for argv in calls if "sysctl" in str(argv)], [])

    def test_an_explicit_queue_dir_beats_codeteam_queue_dir(self):
        other = self.root / "other" / "queue"
        put_job(other, "other-job", job("other-job", state="running", started=NOW - 60, pid=111))
        put_job(self.queue, "mine", job("mine", state="running", started=NOW - 60, pid=111))
        with patch.dict(os.environ, {"CODETEAM_QUEUE_DIR": str(other)}):
            snap = self.snapshot()
        self.assertEqual(tickets(queue_class(snap["builds"]["queue"], "full")["running"]), ["mine"])

    def test_collect_orders_the_queued_jobs_by_the_position_the_file_gives_and_no_position_last(self):
        put_job(self.queue, "t-late", job("t-late", submitted=NOW - 10, position=1))
        put_job(self.queue, "t-early", job("t-early", submitted=NOW - 300, position=5))
        put_job(self.queue, "t-none", job("t-none", submitted=NOW - 600))
        queued = queue_class(self.snapshot()["builds"]["queue"], "full")["queued"]
        self.assertEqual(tickets(queued), ["t-late", "t-early", "t-none"])
        self.assertEqual([q["position"] for q in queued], [1, 5, None])

    def test_collect_narrows_the_waits_and_the_broken_count_to_a_shorter_retention(self):
        (self.run / "queue.toml").write_text("retention_hours = 6\n")
        put_job(self.queue, "d-in", job("d-in", state="done", submitted=NOW - 2 * HOUR - 300,
                                        started=NOW - 2 * HOUR, finished=NOW - 2 * HOUR + 60))
        put_job(self.queue, "d-out", job("d-out", state="done", submitted=NOW - 10 * HOUR - 100,
                                         started=NOW - 10 * HOUR, finished=NOW - 10 * HOUR + 60))
        put_job(self.queue, "b-out", job("b-out", state="broken", finished=NOW - 7 * HOUR))
        full = queue_class(self.snapshot()["builds"]["queue"], "full")
        self.assertEqual(full["waits"]["n"], 1)
        self.assertEqual((full["waits"]["window_h"], full["broken"]), (6, 0))

    def test_the_deck_never_writes_under_run(self):
        put_job(self.queue, "r1", job("r1", state="running", started=NOW - 60, pid=4242, cost=1.0,
                                      env={"K": "v"}))
        put_job(self.queue, "q1", job("q1", submitted=NOW - 30))
        put_job(self.queue, "d1", job("d1", state="done", submitted=NOW - 900, started=NOW - 600,
                                      finished=NOW - 500))
        (self.queue / "half.json").write_text('{"ticket": "t2", "sta')
        (self.queue / ".runner.lock").write_text("")
        write_runner(self.run / "queue-runner.json")
        before = self.record_run()
        cache = self.c.Cache()
        first = self.snapshot(cache=cache)
        self.snapshot(now=NOW + 5, cache=cache)
        self.assertEqual(tickets(queue_class(first["builds"]["queue"], "full")["running"]), ["r1"])
        self.assertEqual(self.record_run(), before)

    def test_the_queue_view_and_the_runner_state_are_recomputed_every_5_seconds(self):
        runner = self.run / "queue-runner.json"
        write_runner(runner, used=1.0, budget=6)
        put_job(self.queue, "q1", job("q1", submitted=NOW - 60))
        cache = self.c.Cache()
        first = self.snapshot(now=NOW, cache=cache)["builds"]["queue"]
        self.assertEqual(tickets(queue_class(first, "full")["queued"]), ["q1"])
        put_job(self.queue, "q2", job("q2", submitted=NOW - 30))
        write_runner(runner, used=4.0, budget=8, beat=NOW + 2)
        held = self.snapshot(now=NOW + 2, cache=cache)["builds"]["queue"]
        self.assertEqual(tickets(queue_class(held, "full")["queued"]), ["q1"])
        self.assertEqual((held["runner"]["used"], held["runner"]["budget"]), (1.0, 6))
        due = self.snapshot(now=NOW + 5, cache=cache)["builds"]["queue"]
        self.assertEqual(tickets(queue_class(due, "full")["queued"]), ["q1", "q2"])
        self.assertEqual((due["runner"]["used"], due["runner"]["budget"]), (4.0, 8))


class ModelTests(unittest.TestCase):
    """model.py: pure functions over plain dicts. Each flag has a fixture that raises it and one that does not."""

    def setUp(self):
        from codeteam2.deck import model
        self.m = model
        self.th = dict(model.THRESHOLDS)

    def _sess(self, status="working", since=NOW - 600, transcript="in-turn", held=0, key="a", **extra):
        sess = {"team": "tessa", "key": key, "name": f"Coord-{key}", "role": "lane", "agent": f"tessa-{key}",
                "cwd": "/t/wt-s", "sid": f"sid-{key}", "herdr": {"status": status, "since": since},
                "transcript_state": transcript, "transcript_mtime": NOW - 60,
                "mail": {"waiting": held, "held": held, "delivered_today": 0, "oldest_waiting_s": None},
                "agents": [], "draft_since": None, "api_error": None, "recent": {"tools": [], "messages": []}}
        sess.update(extra)
        return sess

    def _agent(self, agent_id="a1", finished=False, last_write=NOW - 60, parent=None, last_state="in-turn"):
        return {"id": agent_id, "type": "coder", "description": "", "depth": 2, "parent": parent,
                "finished": finished, "worktree": "/t/wt-a", "started": NOW - HOUR, "last_write": last_write,
                "last_state": last_state, "tokens": None}

    def _team(self, sessions=(), state="up", heartbeat_age_s=5, cap=None, lanes_running=0, disk=None):
        return {"name": "tessa", "state": state, "heartbeat_age_s": heartbeat_age_s, "cap": cap,
                "running": len(sessions), "lanes_running": lanes_running, "mail_waiting": 0, "msgs_last_hour": 0,
                "free_gb": None, "messages": None, "disk": disk, "sessions": list(sessions)}

    def _snap(self, teams=(), free_gb=200.0):
        return {"version": 1, "at": NOW, "teams": list(teams), "volume": {"free_gb": free_gb},
                "builds": {"queue": {}, "warms": [], "largest": [], "procs": {}},
                "disk_at": None, "alerts": []}

    def _kinds(self, snap, th=None):
        th = th or self.th
        self.m.derive(snap, NOW, th)
        return {a["kind"] for a in self.m.alerts(snap, NOW, th)}

    def test_between_turns_when_working_and_the_turn_has_ended(self):
        flags = self.m.session_flags(self._sess("working", transcript="ended"), NOW, self.th)
        self.assertTrue(flags["between_turns"])

    def test_not_between_turns_while_the_turn_runs_or_the_session_is_idle_or_unknown(self):
        for status, transcript in (("working", "in-turn"), ("idle", "ended"), ("working", "?")):
            with self.subTest(status=status, transcript=transcript):
                flags = self.m.session_flags(self._sess(status, transcript=transcript), NOW, self.th)
                self.assertFalse(flags["between_turns"])

    def test_blocked_session_raises_blocked_with_how_long(self):
        flags = self.m.session_flags(self._sess("blocked", since=NOW - 150), NOW, self.th)
        self.assertTrue(flags["blocked"])
        self.assertEqual(flags["blocked_for_s"], 150)

    def test_working_session_is_not_blocked(self):
        flags = self.m.session_flags(self._sess("working"), NOW, self.th)
        self.assertFalse(flags["blocked"])
        self.assertIsNone(flags["blocked_for_s"])

    def test_held_mail_flags_the_session(self):
        self.assertTrue(self.m.session_flags(self._sess(held=2), NOW, self.th)["held"])

    def test_no_held_mail_does_not_flag_the_session(self):
        self.assertFalse(self.m.session_flags(self._sess(held=0), NOW, self.th)["held"])

    def test_agent_with_no_write_for_13_minutes_and_no_build_is_stalled(self):
        agent = self._agent(last_write=NOW - 13 * MIN)
        flags = self.m.agent_flags(agent, [agent], self._sess(), {}, NOW, self.th)
        self.assertTrue(flags["stalled"])

    def test_a_build_in_the_agent_worktree_is_not_a_stall(self):
        agent = self._agent(last_write=NOW - 13 * MIN)
        flags = self.m.agent_flags(agent, [agent], self._sess(), {"/t/wt-a": [4242]}, NOW, self.th)
        self.assertFalse(flags["stalled"])

    def test_a_recent_write_is_not_a_stall(self):
        agent = self._agent(last_write=NOW - 60)
        self.assertFalse(self.m.agent_flags(agent, [agent], self._sess(), {}, NOW, self.th)["stalled"])

    def test_a_finished_agent_is_not_stalled(self):
        agent = self._agent(finished=True, last_write=NOW - 13 * MIN)
        self.assertFalse(self.m.agent_flags(agent, [agent], self._sess(), {}, NOW, self.th)["stalled"])

    def test_subagent_waits_on_a_finished_child_when_its_turn_ended_before_the_child_finished(self):
        parent = self._agent("p1", last_write=NOW - 600, last_state="ended")
        child = self._agent("c1", finished=True, last_write=NOW - 100, parent="p1")
        flags = self.m.agent_flags(parent, [parent, child], self._sess(), {}, NOW, self.th)
        self.assertTrue(flags["waiting_on_finished_child"])

    def test_parent_still_in_turn_is_not_waiting_on_its_child(self):
        parent = self._agent("p1", last_write=NOW - 600, last_state="in-turn")
        child = self._agent("c1", finished=True, last_write=NOW - 100, parent="p1")
        flags = self.m.agent_flags(parent, [parent, child], self._sess(), {}, NOW, self.th)
        self.assertFalse(flags["waiting_on_finished_child"])

    def test_child_finished_before_the_parent_last_wrote_is_not_waiting(self):
        parent = self._agent("p1", last_write=NOW - 600, last_state="ended")
        child = self._agent("c1", finished=True, last_write=NOW - 700, parent="p1")
        flags = self.m.agent_flags(parent, [parent, child], self._sess(), {}, NOW, self.th)
        self.assertFalse(flags["waiting_on_finished_child"])

    def test_session_waits_on_a_finished_child_when_its_turn_ended(self):
        child = self._agent("c1", finished=True, last_write=NOW - 100)
        ended = self._sess("working", transcript="ended", transcript_mtime=NOW - 600, agents=[child])
        self.assertIn("child_finished", self._kinds(self._snap([self._team([ended])])))

    def test_session_in_turn_with_a_finished_child_is_not_waiting(self):
        child = self._agent("c1", finished=True, last_write=NOW - 100)
        in_turn = self._sess("working", transcript="in-turn", transcript_mtime=NOW - 600, agents=[child])
        self.assertNotIn("child_finished", self._kinds(self._snap([self._team([in_turn])])))

    def test_agent_orphaned_when_its_session_has_exited_and_it_is_recent(self):
        agent = self._agent(last_write=NOW - 60)
        self.assertTrue(self.m.agent_flags(agent, [agent], self._sess("absent"), {}, NOW, self.th)["orphan"])

    def test_agent_of_a_working_session_is_not_orphaned(self):
        agent = self._agent(last_write=NOW - 60)
        self.assertFalse(self.m.agent_flags(agent, [agent], self._sess("working"), {}, NOW, self.th)["orphan"])

    def test_blocked_alert_is_raised_past_two_minutes_only(self):
        self.assertIn("blocked", self._kinds(self._snap([self._team([self._sess("blocked", since=NOW - 150)])])))
        self.assertNotIn("blocked", self._kinds(self._snap([self._team([self._sess("blocked", since=NOW - 60)])])))

    def test_held_alert_is_raised_only_with_held_mail(self):
        self.assertIn("held", self._kinds(self._snap([self._team([self._sess(held=2)])])))
        self.assertNotIn("held", self._kinds(self._snap([self._team([self._sess(held=0)])])))

    def test_heartbeat_alert_is_raised_for_an_up_team_only(self):
        self.assertIn("heartbeat", self._kinds(self._snap([self._team(state="up", heartbeat_age_s=90)])))
        self.assertNotIn("heartbeat", self._kinds(self._snap([self._team(state="down", heartbeat_age_s=90)])))

    def test_stalled_alert_is_raised_for_a_silent_subagent(self):
        stalled = self._sess(agents=[self._agent(last_write=NOW - 13 * MIN)])
        quiet = self._sess(agents=[self._agent(last_write=NOW - 60)])
        self.assertIn("stalled", self._kinds(self._snap([self._team([stalled])])))
        self.assertNotIn("stalled", self._kinds(self._snap([self._team([quiet])])))

    def test_disk_low_alert_is_raised_under_50_gb_free(self):
        self.assertIn("disk_low", self._kinds(self._snap(free_gb=30.0)))
        self.assertNotIn("disk_low", self._kinds(self._snap(free_gb=120.0)))

    def test_over_cap_alert_is_raised_past_the_lane_cap(self):
        self.assertIn("over_cap", self._kinds(self._snap([self._team(cap=2, lanes_running=3)])))
        self.assertNotIn("over_cap", self._kinds(self._snap([self._team(cap=2, lanes_running=2)])))

    def test_build_output_alert_follows_the_threshold(self):
        def snap():
            disk = {"size_gb": 1.0, "worktrees": [{"path": "/t/wt-x", "size_gb": 1.0,
                                                   "parts": {"cargo-target": 1.0}}]}
            return self._snap([self._team(disk=disk)])
        self.assertNotIn("build_output", self._kinds(snap()))
        self.assertIn("build_output", self._kinds(snap(), dict(self.th, build_out_alert_gb=0.5)))

    def test_alert_log_keeps_one_line_per_key_with_its_first_seen_time(self):
        log = self.m.AlertLog()
        held = {"key": "held:tessa:Coord-a", "kind": "held", "team": "tessa", "session": "Coord-a",
                "text": "Coord-a has held mail", "since": NOW}
        blocked = {"key": "blocked:tessa:Coord-b", "kind": "blocked", "team": "tessa", "session": "Coord-b",
                   "text": "Coord-b blocked", "since": NOW + 60}
        first = log.update([held], NOW)[0]
        second = log.update([held, blocked], NOW + 60)
        self.assertEqual([x["key"] for x in second], ["blocked:tessa:Coord-b", "held:tessa:Coord-a"])
        self.assertEqual(second[1], first)

    def test_alert_log_keeps_an_alert_after_its_condition_clears(self):
        log = self.m.AlertLog()
        held = {"key": "held:tessa:Coord-a", "kind": "held", "team": "tessa", "session": "Coord-a",
                "text": "Coord-a has held mail", "since": NOW}
        blocked = {"key": "blocked:tessa:Coord-b", "kind": "blocked", "team": "tessa", "session": "Coord-b",
                   "text": "Coord-b blocked", "since": NOW + 60}
        log.update([held, blocked], NOW + 60)
        after = log.update([blocked], NOW + 120)
        self.assertEqual([x["key"] for x in after], ["blocked:tessa:Coord-b", "held:tessa:Coord-a"])

    def test_alert_log_has_one_line_when_a_key_repeats(self):
        log = self.m.AlertLog()
        held = {"key": "held:tessa:Coord-a", "kind": "held", "team": "tessa", "session": "Coord-a",
                "text": "Coord-a has held mail", "since": NOW}
        self.assertEqual([x["key"] for x in log.update([held, dict(held)], NOW)], ["held:tessa:Coord-a"])


def render_session(team, key, name, role, status="working", since=NOW - 600, flags=None, held=0, agents=(),
                   **fields):
    """A session as collect and model give it. `fields` replace whole top-level keys."""
    base = {"between_turns": False, "blocked": False, "blocked_for_s": None, "held": False, "typing": False,
            "api_error": False, "waiting_on_finished_child": False}
    return {"team": team, "key": key, "name": name, "role": role, "agent": f"{team}-{key}",
            "cwd": f"/t/{team}/{key}", "sid": f"sid-{key}", "model": "claude-opus-5-5", "effort": "high",
            "herdr": {"status": status, "since": since}, "transcript_state": "in-turn",
            "transcript_mtime": NOW - 30,
            "context": {"used_pct": 42.0, "window": 1000000, "compactions": 2, "compactions_partial": False},
            "cache": {"warm": True, "expires_in_s": 1200, "hit_ratio": 0.9},
            "cost": {"session_usd": 3.2, "seat_today_usd": 10.1, "seat_today_partial": False},
            "mail": {"waiting": held, "held": held, "delivered_today": 4,
                     "oldest_waiting_s": 300 if held else None},
            "draft_since": None, "api_error": None, "idle_exit_in_s": None,
            "recent": {"tools": [{"name": "Bash", "summary": "pytest -q"}], "messages": []},
            "agents": list(agents), "flags": {**base, **(flags or {})}, **fields}


def render_agent(agent_id="a1", **fields):
    return {"id": agent_id, "type": "coder",
            "description": "port the parser to the new store API, then fix the three failing tests in the lane",
            "depth": 2, "parent": None, "finished": False, "worktree": "/t/alpha/wt", "started": NOW - 900,
            "last_write": NOW - 40, "last_state": "in-turn", "tokens": 12345,
            "flags": {"stalled": False, "waiting_on_finished_child": False, "orphan": False}, **fields}


def render_messages():
    """alpha's messages: two in the log, one from a session of the team (Orc-Alpha, an orc) and one from a sender
    that is not a session of the team."""
    return {"hourly": [i % 5 for i in range(24)], "last_hour": 7,
            "top_senders": [["Orc-Alpha", 5], ["Coord-a", 3]], "top_recipients": [["Coord-a", 4]],
            "broadcasts_today": 1, "queued": 2, "held": 2, "delivered_today": 9,
            "last": [{"id": 9, "ts": NOW - 60, "sender": "Orc-Alpha", "kind": "REQUEST", "recipient": "Coord-a",
                      "text": "check the dialog on the screen now"},
                     {"id": 8, "ts": NOW - 120, "sender": "Stranger", "kind": "NOTE", "recipient": "all",
                      "text": "a broadcast"}],
            "by_target": {"a": {"waiting": 2, "held": 2, "delivered_today": 4, "oldest_waiting_ts": iso(NOW - 600)}},
            "max_id": 40}


def render_job(ticket, cls, state, **fields):
    """A job as read_queue gives it: the whitelisted fields, times in epoch seconds, kind run and no position or hold
    unless the fields say so. A queued job carries position and waiting_s, a running one running_s and pid_alive; the
    panel reads those, not the file."""
    return {"ticket": ticket, "class": cls, "state": state, "kind": "run", "team": "alpha", "session": "Coord-b",
            "worktree": f"/t/alpha/{ticket}", "submitted": NOW - 900, "started": None, "finished": None, "pid": None,
            "cost": None, "estimated_start": None, "position": None, "hold": None, **fields}


def render_class(name, ceiling, running=(), queued=(), n=0, median_s=None, max_s=None, broken=0, guaranteed=1,
                 window_h=24):
    """A class as read_queue gives it. held counts the queued jobs by their hold, as read_queue does."""
    held = {hold: sum(1 for job in queued if job["hold"] == hold) for hold in ("warm", "load", "swap")}
    return {"class": name, "guaranteed": guaranteed, "ceiling": ceiling, "running": list(running),
            "queued": list(queued), "waits": {"n": n, "median_s": median_s, "max_s": max_s, "window_h": window_h},
            "broken": broken, "held": held}


def render_runner(**fields):
    """A runner as read_runner gives it: live, with the budget in use, load and swap and the holds the runner reports.
    The box prints no load reading and shows a last-beat age for a stale runner."""
    return {"state": "live", "pid": 111, "beat_age_s": 5, "budget": 6, "used": 3.0, "load": 12.34, "load_max": 36,
            "swap": 0.5, "swap_max": 0.9, "load_hold": True, "swap_hold": True, **fields}


def render_queue():
    """builds["queue"] in read_queue's shape, with a live runner. full runs a job and has three waits in 24 h; post is
    idle; pre has a broken job and no waits; dev has a ceiling of 0 and runs a slot job (pid gone) and a run whose cost
    is not known. It queues three: a slot held for the warm, one with no estimated start, one with no position. One
    unreadable file."""
    running_full = render_job("f-run", "full", "running", kind="run", team="alpha", session="Coord-a",
                              started=NOW - 600, pid=4242, cost=4.0, running_s=600, pid_alive=True)
    running_slot = render_job("d-run", "dev", "running", kind="slot", started=NOW - 60, pid=9999, cost=1.0,
                              running_s=60, pid_alive=False)
    running_dev = render_job("d-run2", "dev", "running", session="Coord-c", started=NOW - 300, pid=5555,
                             running_s=300, pid_alive=True)
    queued_1 = render_job("d-q1", "dev", "queued", kind="slot", submitted=NOW - 200, estimated_start=NOW + 1800,
                          position=1, waiting_s=200, hold="warm")
    queued_2 = render_job("d-q2", "dev", "queued", session="Orc-Alpha", submitted=NOW - 100, position=2, waiting_s=100)
    queued_3 = render_job("d-q3", "dev", "queued", session="Coord-c", submitted=NOW - 50, waiting_s=50)
    return {"state": "ok", "unknown": 1, "runner": render_runner(),
            "classes": [render_class("full", 1, [running_full], n=3, median_s=120.0, max_s=600.0),
                        render_class("post", 2),
                        render_class("pre", 2, broken=1),
                        render_class("dev", 0, [running_slot, running_dev], [queued_1, queued_2, queued_3])]}


def render_empty_queue():
    """read_queue's shape with nothing in it: no jobs, no waits, no broken jobs, no unreadable file, and no runner."""
    runner = {key: None for key in RUNNER_KEYS} | {"state": "none"}
    return {"state": "ok", "unknown": 0, "runner": runner,
            "classes": [render_class(name, 1) for name in ("full", "post", "pre", "dev")]}


def row_text(row):
    return "".join(text for text, _ in row)


def has(colour, word):
    """A colour is None or space-separated words (a palette word and/or bold): membership, never equality."""
    return word in (colour or "").split()


def colour_text(row, word):
    """The text of the row's segments whose colour carries `word`."""
    return "".join(text for text, colour in row if has(colour, word))


def colour_at(row, col):
    """The colour of the segment under column `col`."""
    for text, colour in row:
        if col < len(text):
            return colour
        col -= len(text)
    raise AssertionError(f"column past the end of {row_text(row)!r}")


def colour_of(row, needle, start=0):
    """The colour under the first character of `needle`, searched from column `start`."""
    col = row_text(row).find(needle, start)
    if col < 0:
        raise AssertionError(f"{needle!r} not in {row_text(row)[start:]!r}")
    return colour_at(row, col)


def hhmm(ts, secs=False):
    return dt.datetime.fromtimestamp(ts).astimezone().strftime("%H:%M:%S" if secs else "%H:%M")


def find_box(texts, title):
    """(row, left corner column, right corner column) of the first box whose top border carries `title`."""
    for y, line in enumerate(texts):
        at = line.find(title)
        while at >= 0:
            x0 = line.rfind("╭", 0, at)
            if x0 >= 0 and set(line[x0 + 1:at]) <= {"─", " "}:
                return y, x0, line.index("╮", at)
            at = line.find(title, at + 1)
    raise AssertionError(f"no box titled {title!r} in:\n" + "\n".join(texts))


def broken_boxes(texts):
    """Every box fault: a top corner with no right corner, a side row whose ends are not `│`, a box that never
    closes, or corners that do not pair up."""
    faults = []
    for y, line in enumerate(texts):
        for x0, char in enumerate(line):
            if char != "╭":
                continue
            x1 = line.find("╮", x0)
            if x1 < 0:
                faults.append(f"row {y}: no ╮ after column {x0}: {line!r}")
                continue
            for yy in range(y + 1, len(texts)):
                row = texts[yy].ljust(x1 + 1)
                if row[x0] == "╰" and row[x1] == "╯" and set(row[x0 + 1:x1]) == {"─"}:
                    break
                if row[x0] != "│" or row[x1] != "│":
                    faults.append(f"row {yy}: the box from row {y} needs │ at {x0} and {x1}: {texts[yy]!r}")
                    break
            else:
                faults.append(f"the box at row {y} column {x0} never closes")
    counts = {corner: sum(t.count(corner) for t in texts) for corner in "╭╮╰╯"}
    if len(set(counts.values())) > 1:
        faults.append(f"corners do not pair up: {counts}")
    return faults


def render_snapshot():
    """Three teams. alpha is up: Orc-Alpha (orc) between turns; Coord-a (lane) blocked 3m with held mail, context
    85% and two subagents; Coord-b (lane, Sonnet, max effort, cold cache) idle, typing, with an api error and an idle
    exit. beta is down with one session (Kong, guard) whose fields are unknown; its messages, disk and free space are
    None (failed sources). gamma is HALTED with no sessions, mail waiting and the largest disk. Two alerts."""
    alpha = {"name": "alpha", "manifest": "/m/alpha.toml", "home": "/t/alpha/team", "root": "/t/alpha",
             "state": "up", "heartbeat_age_s": 5, "cap": 2, "running": 3, "lanes_running": 1, "mail_waiting": 2,
             "msgs_last_hour": 7, "free_gb": 300.0, "messages": render_messages(),
             "disk": {"size_gb": 80.0,
                      "worktrees": [{"path": "/t/alpha/wt", "size_gb": 40.0, "parts": {"cargo-target": 12.0}},
                                    {"path": "/t/alpha/wt2", "size_gb": 6.0, "parts": {"target": 2.0}}]},
             "sessions": [
                 render_session("alpha", "orc", "Orc-Alpha", "orc", flags={"between_turns": True},
                                recent={"tools": [{"name": "Read", "summary": "render.py"}],
                                        "messages": [{"dir": "out", "ts": NOW - 120, "peer": "Coord-a",
                                                      "kind": "REQUEST", "text": "look again"}]}),
                 render_session("alpha", "a", "Coord-a", "lane", status="blocked", since=NOW - 400, held=2,
                                flags={"blocked": True, "blocked_for_s": 180, "held": True},
                                agents=[render_agent(),
                                        render_agent("a2", type="tester", description="baseline tests", depth=1,
                                                     finished=True, started=NOW - 1200, last_write=NOW - 1000,
                                                     tokens=500)],
                                context={"used_pct": 85.0, "window": 1000000, "compactions": 2,
                                         "compactions_partial": False}),
                 render_session("alpha", "b", "Coord-b", "lane", status="idle", since=NOW - 60,
                                flags={"typing": True, "api_error": True},
                                model="claude-sonnet-4-6", effort="max",
                                cache={"warm": False, "expires_in_s": None, "hit_ratio": None},
                                cost={"session_usd": 3.2, "seat_today_usd": 10.1, "seat_today_partial": True},
                                context={"used_pct": 60.0, "window": 1000000, "compactions": 2,
                                         "compactions_partial": True},
                                draft_since=NOW - 20, api_error="overloaded", idle_exit_in_s=18000,
                                recent={"tools": [], "messages": []})]}
    beta = {"name": "beta", "manifest": "/m/beta.toml", "home": "/t/beta/team", "root": "/t/beta", "state": "down",
            "heartbeat_age_s": None, "cap": None, "running": 0, "lanes_running": 0, "mail_waiting": None,
            "msgs_last_hour": None, "free_gb": None, "messages": None, "disk": None,
            "sessions": [render_session("beta", "kong", "Kong", "guard", status="?", since=None, model=None,
                                        effort=None, context=None,
                                        cost={"session_usd": None, "seat_today_usd": None,
                                              "seat_today_partial": False})]}
    gamma = {"name": "gamma", "manifest": "/m/gamma.toml", "home": "/t/gamma/team", "root": "/t/gamma",
             "state": "HALTED", "heartbeat_age_s": 8040, "cap": 3, "running": 0, "lanes_running": 0,
             "mail_waiting": 3, "msgs_last_hour": 0, "free_gb": 300.0, "messages": None,
             "disk": {"size_gb": 95.0, "worktrees": []}, "sessions": []}
    builds = {"queue": render_queue(),
              "warms": [{"state": "held", "worktree": "/t/alpha/wt2", "elapsed_s": 100}],
              "largest": [{"path": "/t/alpha/wt", "part": "cargo-target", "size_gb": 12.0}], "procs": {}}
    alerts = [{"key": "build_output:alpha:/t/alpha/wt", "kind": "build_output", "team": "alpha", "session": None,
               "text": "/t/alpha/wt build output 12.0 GB", "since": NOW - 60},
              {"key": "blocked:alpha:Coord-a", "kind": "blocked", "team": "alpha", "session": "Coord-a",
               "text": "Coord-a blocked for 3 min: a dialog is waiting on its screen, answer it or tell the owner, now",
               "since": NOW - 180}]
    return {"version": 1, "at": NOW, "took_s": 0.1, "errors": [], "volume": {"free_gb": 300.0},
            "teams": [alpha, beta, gamma], "builds": builds, "disk_at": NOW - 600, "alerts": alerts}


def tall_snapshot():
    """render_snapshot plus delta, an up team with 30 sessions (Coord-d00..Coord-d29, the last visible ones), and 60
    more queued dev jobs: taller than any screen, so pinning has to scroll and the job strip has to be cut."""
    snap = render_snapshot()
    sessions = [render_session("delta", f"d{n:02d}", f"Coord-d{n:02d}", "lane") for n in range(30)]
    snap["teams"].append({"name": "delta", "manifest": "/m/delta.toml", "home": "/t/delta/team", "root": "/t/delta",
                          "state": "up", "heartbeat_age_s": 3, "cap": 4, "running": 30, "lanes_running": 2,
                          "mail_waiting": 0, "msgs_last_hour": 3, "free_gb": 300.0, "messages": render_messages(),
                          "disk": None, "sessions": sessions})
    queue_class(snap["builds"]["queue"], "dev")["queued"] += [
        render_job(f"d-x{n}", "dev", "queued", position=n + 3, waiting_s=10) for n in range(60)]
    return snap


# The space budget's worst case (plan, Rework 2): names at their caps, 3-digit counts, `23h59m` durations.
STRESS_TEAM, STRESS_TEAM2 = "stress-team-name", "second-team-long"
STRESS_HALTED, STRESS_DOWN = "halted-team-name", "down-team-name-x"
DAY_S = 86340
DAY = "23h59m"
# One session per badge, first-that-applies order; Lane01 has every flag set. Names are 20 cells, distinct in their
# first 11 (what a name column at its floor of 12 keeps before the `…`).
STRESS_BADGES = {1: "child done", 2: "blocked", 3: "held 123", 4: "typing", 5: "api error", 6: f"✉123 {DAY}",
                 7: f"exit {DAY}"}
STRESS_STATE = {1: "■ blocked", 2: "■ blocked", 3: "● working", 4: "● working", 5: "○ idle", 6: "● working",
                7: "○ idle"}
# Sizes in no BUILD_PARTS order, so largest-first is visible; together they cannot fit a 49-cell body.
STRESS_PARTS = {"cargo-target": 12.1, "target": 98.7, ".build": 3.4, "node_modules": 123.4, ".codegraph": 45.6,
                "scratchpad": 10.5}
STRESS_HOLDS = ("warm", "load", "swap", None)
# Every BUILD_PARTS, in no BUILD_PARTS order, 4-digit sizes: about 110 cells together, wider than any body, while
# the widest item (`node_modules 2345.6G`, 20 cells) still fits the 30-column body (26) less its 2-cell indent.
WRAP_PARTS = {"cargo-target": 345.6, "target": 1234.5, ".build": 7.8, "node_modules": 2345.6, ".codegraph": 56.7,
              "scratchpad": 123.4}
BUILD_PARTS = tuple(WRAP_PARTS)
_WORKTREE_ROW = re.compile(r"^  (?P<tail>\S+) (?P<size>\d+\.\dG)(?P<rest>.*)$")
_PART_ITEM = re.compile(r"(\S+) (\d+\.\dG)")


def disk_blocks(bodies):
    """{path tail: (size, ["<part> <size>", ...])} for each DISK worktree row: the parts on its own row, then on the
    continuation rows right under it (indented, starting with a build part). Any other row ends the block, so a part
    cut mid-field or shown under another worktree is missing from its block."""
    blocks, current = {}, None
    for body in bodies:
        lead = _PART_ITEM.match(body.lstrip())
        if current is not None and body.startswith("  ") and lead and lead[1] in BUILD_PARTS:
            current += [" ".join(item) for item in _PART_ITEM.findall(body)]
            continue
        row = _WORKTREE_ROW.match(body)
        if row and row["tail"] not in BUILD_PARTS:
            current = [" ".join(item) for item in _PART_ITEM.findall(row["rest"])]
            blocks[row["tail"]] = (row["size"], current)
        else:
            current = None
    return blocks


def stress_name(n, kind="Lane"):
    return f"{kind}{n:02d}-session-names"


def stress_session(n):
    name, mail = stress_name(n), {"waiting": 0, "held": 0, "delivered_today": 123, "oldest_waiting_s": None}
    fields = {"since": NOW - DAY_S, "cost": {"session_usd": 123.45, "seat_today_usd": 123.45,
                                             "seat_today_partial": True},
              "context": {"used_pct": 100.0, "window": 1000000, "compactions": 123, "compactions_partial": True}}
    if n == 1:
        flags = {"waiting_on_finished_child": True, "blocked": True, "blocked_for_s": DAY_S, "held": True,
                 "typing": True, "api_error": True}
        mail = {"waiting": 123, "held": 123, "delivered_today": 123, "oldest_waiting_s": DAY_S}
        tools = [{"name": f"Tool{i}", "summary": f"summary of the tool call number {i}"} for i in range(5)]
        msgs = [{"dir": "in" if i % 2 else "out", "ts": NOW - 60 * i, "peer": stress_name(2), "kind": "REQUEST",
                 "text": f"message number {i} of the detail"} for i in range(5)]
        fields.update(status="blocked", role="designer", effort="xhigh", draft_since=NOW - 20, api_error="overloaded",
                      idle_exit_in_s=DAY_S, recent={"tools": tools, "messages": msgs})
    elif n == 2:
        flags = {"blocked": True, "blocked_for_s": DAY_S}
        fields["status"] = "blocked"
    elif n == 3:
        flags = {"held": True}
        mail = {"waiting": 123, "held": 123, "delivered_today": 123, "oldest_waiting_s": DAY_S}
    elif n == 4:
        flags = {"typing": True}
        fields["draft_since"] = NOW - 20
    elif n == 5:
        flags = {"api_error": True}
        fields.update(status="idle", api_error="overloaded")
    elif n == 6:
        flags = {}
        mail = {"waiting": 123, "held": 0, "delivered_today": 123, "oldest_waiting_s": DAY_S}
    else:
        flags = {}
        fields.update(status="idle", idle_exit_in_s=DAY_S)
    role = fields.pop("role", "lane")
    return render_session(STRESS_TEAM, f"s{n}", name, role, flags=flags, mail=mail, **fields)


def stress_snapshot():
    """The worst case the screen must survive: stress-team-name (up, loop 23h59m) with one session per badge
    (Lane01 has every flag, held mail, and 5 tools and 5 messages of detail), second-team-long (up) with 20 sessions
    to scroll, two teams not up with 3-digit mail; every BUILD_PARTS on a worktree; a running job whose pid is gone,
    12 queued jobs at 2-digit positions with holds, waits of 123 at 23h59m; 123 alerts and 123 source errors."""
    messages = {"hourly": [i % 7 for i in range(24)], "last_hour": 123,
                "top_senders": [[stress_name(i), 123] for i in range(1, 6)],
                "top_recipients": [[stress_name(i), 123] for i in range(1, 6)],
                "broadcasts_today": 123, "queued": 123, "held": 123, "delivered_today": 123, "max_id": 999,
                "last": [{"id": 900 + i, "ts": NOW - 60 * i, "sender": stress_name(i % 7 + 1),
                          "kind": "REQUEST", "recipient": stress_name((i + 1) % 7 + 1),
                          "text": "a message long enough to need cutting in any box of the deck"} for i in range(10)],
                "by_target": {}}
    worktree = "/t/stress/worktree-with-a-very-long-name"
    stress = {"name": STRESS_TEAM, "manifest": "/m/s.toml", "home": "/t/stress/team", "root": "/t/stress",
              "state": "up", "heartbeat_age_s": DAY_S, "cap": 123, "running": 7, "lanes_running": 12,
              "mail_waiting": 123, "msgs_last_hour": 123, "free_gb": 300.0, "messages": messages,
              "disk": {"size_gb": 456.7,
                       "worktrees": [{"path": worktree, "size_gb": 234.5, "parts": dict(STRESS_PARTS)},
                                     {"path": "/t/stress/second-worktree-long-name", "size_gb": 6.0,
                                      "parts": {"target": 2.0}}]},
              "sessions": [stress_session(n) for n in range(1, 8)]}
    second = {"name": STRESS_TEAM2, "manifest": "/m/s2.toml", "home": "/t/second/team", "root": "/t/second",
              "state": "up", "heartbeat_age_s": 5, "cap": 4, "running": 20, "lanes_running": 2, "mail_waiting": 0,
              "msgs_last_hour": 3, "free_gb": 300.0, "messages": render_messages(), "disk": None,
              "sessions": [render_session(STRESS_TEAM2, f"c{n}", stress_name(n, "Crew"), "lane")
                           for n in range(1, 21)]}
    halted = {"name": STRESS_HALTED, "manifest": "/m/h.toml", "home": "/t/h/team", "root": "/t/h",
              "state": "HALTED", "heartbeat_age_s": DAY_S, "cap": 3, "running": 0, "lanes_running": 0,
              "mail_waiting": 123, "msgs_last_hour": 0, "free_gb": 300.0, "messages": None,
              "disk": {"size_gb": 789.0, "worktrees": []}, "sessions": []}
    down = {"name": STRESS_DOWN, "manifest": "/m/d.toml", "home": "/t/d/team", "root": "/t/d", "state": "down",
            "heartbeat_age_s": None, "cap": None, "running": 0, "lanes_running": 0, "mail_waiting": 456,
            "msgs_last_hour": None, "free_gb": None, "messages": None, "disk": None, "sessions": []}
    gone = render_job("r-gone", "full", "running", kind="slot", team=STRESS_TEAM, session=stress_name(1),
                      worktree=worktree, started=NOW - DAY_S, pid=4242, cost=123.4, running_s=DAY_S,
                      pid_alive=False)
    alive = render_job("r-alive", "dev", "running", team=STRESS_TEAM, session=stress_name(2), worktree=worktree,
                       started=NOW - 600, pid=5555, cost=12.3, running_s=600, pid_alive=True)
    queued = [render_job(f"q{n}", "dev", "queued", team=STRESS_TEAM, session=stress_name(n % 7 + 1),
                         worktree=worktree, estimated_start=NOW + 1800, position=n, waiting_s=DAY_S,
                         hold=STRESS_HOLDS[n % 4]) for n in range(10, 22)]
    queue = {"state": "ok", "unknown": 123, "runner": render_runner(),
             "classes": [render_class("full", 1, [gone], n=123, median_s=DAY_S, max_s=DAY_S),
                         render_class("post", 2), render_class("pre", 2, broken=123),
                         render_class("dev", 0, [alive], queued)]}
    builds = {"queue": queue, "warms": [{"state": "held", "worktree": worktree, "elapsed_s": DAY_S}],
              "largest": [{"path": worktree, "part": "node_modules", "size_gb": 111.1}], "procs": {}}
    alerts = [{"key": f"held:{STRESS_TEAM}:{n}", "kind": "held", "team": STRESS_TEAM, "session": stress_name(3),
               "text": f"held mail number {n} for a session with a long name", "since": NOW - n} for n in range(123)]
    return {"version": 1, "at": NOW, "took_s": 0.1, "errors": [f"source {n} failed" for n in range(123)],
            "volume": {"free_gb": 300.0}, "teams": [stress, second, halted, down], "builds": builds,
            "disk_at": NOW - 600, "alerts": alerts}


def a_session(snap, name):
    return next(s for t in snap["teams"] for s in t["sessions"] if s["name"] == name)


def a_team(snap, name):
    return next(t for t in snap["teams"] if t["name"] == name)


# The left column at 120 columns is width - 54; the right one starts after a one-column gap.
LEFT_120 = 66
GOLDEN = Path(__file__).resolve().parent / "deck_golden_120.txt"
KEY_LINE = "↑↓ j k move   ⏎ expand   a all agents   t team   d disk now   q quit"
CURSOR = {"Orc-Alpha": 0, "Coord-a": 1, "Coord-b": 2, "Kong": 3}


class RenderCase(unittest.TestCase):
    """What every render test class shares: the module, the fixture and ways to find a box or a row on screen."""

    def setUp(self):
        from codeteam2.deck import render
        self.r = render
        self.snap = render_snapshot()

    def rows(self, snap=None, width=120, **kwargs):
        return self.r.render(self.snap if snap is None else snap, width, **kwargs)

    def texts(self, snap=None, width=120, **kwargs):
        return [row_text(row) for row in self.rows(snap, width, **kwargs)]

    def screen(self, snap=None, width=120, **kwargs):
        return "\n".join(self.texts(snap, width, **kwargs))

    def box(self, rows, title):
        """The rows of the box titled `title`, top to bottom: (screen row, text cut to the box, left column)."""
        texts = [row_text(row) for row in rows]
        y, x0, x1 = find_box(texts, title)
        out = []
        for row, text in zip(rows[y:], texts[y:]):
            out.append((row, text[x0:x1 + 1], x0))
            if len(out) > 1 and text[x0:x0 + 1] == "╰":
                break
        return out

    def box_text(self, rows, title):
        return "\n".join(text for _, text, _ in self.box(rows, title))

    def line(self, box, needle):
        """The one box line holding needle: (screen row, box text, left column)."""
        found = [entry for entry in box if needle in entry[1]]
        self.assertEqual(len(found), 1, f"box lines holding {needle!r}: {[e[1] for e in box]}")
        return found[0]

    def assertInOrder(self, text, *parts):
        at = 0
        for part in parts:
            found = text.find(part, at)
            self.assertGreaterEqual(found, 0, f"{part!r} not after column {at} in {text!r}")
            at = found + len(part)

    def assertWord(self, colour, word, what=""):
        self.assertTrue(has(colour, word), f"{what}: colour {colour!r} lacks {word!r}")


class RenderTests(RenderCase):
    """render.py: widths, boxes, the header, legend and key line, the golden file, sparkline."""

    def test_no_row_is_wider_than_the_screen_and_every_box_is_intact(self):
        views = ({}, {"cursor": 1, "expanded": {"alpha/a", "alpha/orc"}}, {"cursor": 3, "all_agents": True})
        for name, snap in (("render", render_snapshot()), ("tall", tall_snapshot())):
            for width in (30, 80, 120, 180, 240):
                for view in views:
                    with self.subTest(snap=name, width=width, view=view):
                        texts = self.texts(snap, width, **view)
                        self.assertEqual([t for t in texts if len(t) > width], [])
                        self.assertEqual(broken_boxes(texts), [])
                        find_box(texts, "FLEET")
                        find_box(texts, "ALERTS")

    def test_below_30_columns_nothing_raises_and_no_row_is_wider(self):
        for width in (1, 10, 20, 29):
            for height in (None, 8):
                with self.subTest(width=width, height=height):
                    texts = self.texts(tall_snapshot(), width, cursor=5, height=height)
                    self.assertEqual([t for t in texts if len(t) > width], [])

    def test_every_session_name_and_every_box_title_shows_at_80(self):
        text = self.screen(width=80, cursor=1)
        for name in ("Orc-Alpha", "Coord-a", "Coord-b", "Kong"):
            self.assertIn(name, text)
        texts = self.texts(width=80, cursor=1)
        for title in ("FLEET", "alpha · 3 sessions", "beta · 1 session", "halted", "Opus 5.5 · Coord-a",
                      "BUILDS · queue", "log · alpha", "DISK", "ALERTS"):
            find_box(texts, title)
        self.assertIn("agents · ", text)

    def test_blocked_and_held_segments_are_salmon(self):
        salmon = "".join(colour_text(row, "salmon") for row in self.rows(cursor=1))
        self.assertIn("blocked", salmon)
        self.assertIn("held", salmon)

    def test_a_failed_source_shows_a_question_mark(self):
        healthy = copy.deepcopy(self.snap)
        a_team(healthy, "beta").update({"messages": render_messages(), "free_gb": 300.0, "heartbeat_age_s": 5,
                                        "mail_waiting": 0, "msgs_last_hour": 0, "cap": 2,
                                        "disk": {"size_gb": 1.0, "worktrees": []}})
        a_session(healthy, "Kong")["herdr"]["status"] = "idle"
        self.assertGreater(self.screen().count("?"), self.screen(healthy).count("?"))

    def test_a_panel_with_nothing_to_show_takes_no_rows(self):
        bare = copy.deepcopy(self.snap)
        for team in bare["teams"]:
            for session in team["sessions"]:
                session["agents"] = []
        self.assertIn("agents · ", self.screen(cursor=1, all_agents=True))
        self.assertNotIn("agents · ", self.screen(bare, cursor=1, all_agents=True))

    def test_a_sparse_snapshot_renders_without_raising(self):
        sparse = {"teams": [{"name": "t", "sessions": [{"name": "Coord-a", "herdr": {}}]}]}
        for snap in (sparse, {"teams": []}, {}):
            for width in (30, 80, 120, 180):
                for height in (None, 10):
                    with self.subTest(snap=snap, width=width, height=height):
                        rows = self.r.render(snap, width, height=height)
                        self.assertIsInstance(rows, list)
                        self.assertEqual([r for r in rows if len(row_text(r)) > width], [])

    def test_sparkline_has_one_character_per_count_and_a_zero_is_a_dot(self):
        for counts in ([], [0] * 24, [1, 5, 9], list(range(24)), ["x", None, 3]):
            with self.subTest(counts=counts):
                line = self.r.sparkline(counts)
                self.assertEqual(len(line), len(counts))
                self.assertTrue(set(line) <= set("·▁▂▃▄▅▆▇█"), line)
        self.assertEqual(self.r.sparkline([0, 0]), "··")
        self.assertEqual(self.r.sparkline(["x", None, 3]), "··█")
        self.assertEqual(self.r.sparkline([1, 5, 9])[-1], "█")

    def test_the_render_at_120_matches_the_golden_file(self):
        self.assertTrue(GOLDEN.exists(), f"{GOLDEN} is missing: the coder writes it from the finished render")
        got = "\n".join(row_text(row) for row in self.r.render(render_snapshot(), 120)) + "\n"
        self.assertEqual(got, GOLDEN.read_text(encoding="utf-8"))

    def test_the_header_counts_up_halted_lanes_and_alerts_with_the_clock(self):
        row = self.rows()[0]
        self.assertInOrder(row_text(row), "CODETEAM DECK", "1 UP", "2 HALTED", "1 LANES WORKING", "▲ 2 ALERTS",
                           hhmm(NOW))
        for word, colour in (("UP", "green"), ("HALTED", "salmon"), ("LANES", "blue"), ("ALERTS", "amber")):
            self.assertWord(colour_of(row, word), colour, word)
            self.assertWord(colour_of(row, word), "bold", word)

    def test_the_header_names_the_team_filter_and_the_source_errors(self):
        snap = copy.deepcopy(self.snap)
        snap["errors"] = ["ps failed"]
        row = self.rows(snap, team_filter="alpha")[0]
        self.assertInOrder(row_text(row), hhmm(NOW), "team alpha", "1 source errors")
        self.assertWord(colour_of(row, "team alpha"), "blue", "team")
        self.assertWord(colour_of(row, "1 source errors"), "salmon", "errors")

    def test_the_legend_keys_the_roles_by_colour_then_the_state_glyphs_then_a_blank_row(self):
        rows = self.rows()
        legend = rows[1]
        self.assertInOrder(row_text(legend), "■ orc", "■ designer", "■ guard", "■ lane", "■ crew", "● working",
                           "◐ between turns", "○ idle", "✓ done", "■ blocked")
        for role, colour in (("orc", "coral"), ("designer", "purple"), ("guard", "teal"), ("lane", "blue"),
                             ("crew", "dim")):
            self.assertWord(colour_of(legend, f"■ {role}"), colour, role)
        self.assertEqual(row_text(rows[2]).strip(), "")

    def test_the_key_line_is_the_last_row_centred(self):
        last = self.texts()[-1]
        self.assertEqual(last.strip(), KEY_LINE)
        self.assertLessEqual(abs(len(last) - len(last.lstrip()) - (120 - len(KEY_LINE)) // 2), 1, last)


class RenderFleetTests(RenderCase):
    """The FLEET box: one cell per team, the free space and the loops."""

    def test_each_team_has_a_cell_with_its_state_lanes_and_mail(self):
        text = self.box_text(self.rows(), "FLEET · 3 teams")
        for fact in ("● alpha", "1/2", "✉2", "7/h", "■ beta", "down", "loop off", "■ gamma", "halted", "✉3",
                     "300G free", "all beating"):
            self.assertIn(fact, text)

    def test_the_cell_colours(self):
        box = self.box(self.rows(), "FLEET · 3 teams")
        top, x0 = box[0][0], box[0][2]
        self.assertWord(colour_of(top, "all beating", x0), "green", "all beating")
        first, second, third = (entry[0] for entry in box[1:4])
        self.assertWord(colour_of(first, "● alpha", x0), "green", "up dot")
        self.assertWord(colour_of(first, "alpha", x0), "bold", "up name")
        self.assertWord(colour_of(first, "■ beta", x0), "salmon", "down glyph")
        self.assertWord(colour_of(second, "halted", x0), "salmon", "halted")
        self.assertWord(colour_of(third, "✉3", x0), "amber", "mail waiting on a halted team")

    def test_a_late_loop_is_named_in_salmon_instead_of_all_beating(self):
        snap = copy.deepcopy(self.snap)
        a_team(snap, "alpha")["heartbeat_age_s"] = 90
        top = self.box(self.rows(snap), "FLEET · 3 teams")[0]
        self.assertNotIn("all beating", top[1])
        self.assertWord(colour_of(top[0], "alpha", top[1].index("loops") + top[2]), "salmon", "late loop")

    def test_low_or_unknown_free_space(self):
        snap = copy.deepcopy(self.snap)
        snap["volume"]["free_gb"] = 30.0
        top = self.box(self.rows(snap), "FLEET · 3 teams")[0]
        self.assertWord(colour_of(top[0], "30", top[2]), "salmon", "free < 50 GB")
        snap["volume"]["free_gb"] = None
        self.assertRegex(self.box(self.rows(snap), "FLEET · 3 teams")[0][1], r"\?G? free")

    def test_lanes_over_the_cap_are_salmon(self):
        snap = copy.deepcopy(self.snap)
        a_team(snap, "alpha")["lanes_running"] = 3
        row, text, x0 = self.line(self.box(self.rows(snap), "FLEET · 3 teams"), "3/2")
        self.assertWord(colour_of(row, "3/2", x0), "salmon", "over cap")

    def test_up_teams_come_first_by_sessions_running_then_the_rest_in_snapshot_order(self):
        names = self.box(self.rows(), "FLEET · 3 teams")[1][1]
        self.assertLess(names.index("alpha"), names.index("beta"))
        self.assertLess(names.index("beta"), names.index("gamma"))
        snap = copy.deepcopy(self.snap)
        a_team(snap, "beta").update(state="up", running=5)
        names = self.box(self.rows(snap), "FLEET · 3 teams")[1][1]
        self.assertLess(names.index("beta"), names.index("alpha"))
        self.assertLess(names.index("alpha"), names.index("gamma"))

    def test_cells_wrap_onto_more_rows_when_they_do_not_fit(self):
        box = self.box(self.rows(width=30), "FLEET")
        text = "\n".join(entry[1] for entry in box)
        for name in ("alpha", "beta", "gamma"):
            self.assertIn(name, text)
        self.assertGreater(len(box), 5, text)


class RenderTeamBoxTests(RenderCase):
    """A team box: title, lanes, mail and cost, the sparkline, and one short row per session."""

    def test_the_title_shows_the_name_the_sessions_and_the_loop(self):
        row, text, x0 = self.box(self.rows(), "alpha · 3 sessions")[0]
        self.assertInOrder(text, "alpha · 3 sessions", "● up · loop 5s")
        self.assertWord(colour_of(row, "● up", x0), "green", "up")

    def test_a_team_that_is_not_up_shows_its_state_in_salmon(self):
        row, text, x0 = self.box(self.rows(), "beta · 1 session")[0]
        self.assertWord(colour_of(row, "down", x0 + text.index("session")), "salmon", "down")

    def test_a_late_loop_is_salmon_and_an_unknown_one_a_question_mark(self):
        snap = copy.deepcopy(self.snap)
        a_team(snap, "alpha")["heartbeat_age_s"] = 90
        row, text, x0 = self.box(self.rows(snap), "alpha · 3 sessions")[0]
        self.assertTrue(colour_text(row, "salmon").strip(), text)
        a_team(snap, "alpha")["heartbeat_age_s"] = None
        self.assertIn("loop ?", self.box(self.rows(snap), "alpha · 3 sessions")[0][1])

    def test_line_one_shows_lanes_mail_and_the_cost_today(self):
        row, text, x0 = self.box(self.rows(), "alpha · 3 sessions")[1]
        self.assertInOrder(text, "1/2 lanes", "✉ 2", "$9.60 today")
        self.assertWord(colour_of(row, "✉ 2", x0), "amber", "mail")
        self.assertWord(colour_of(row, "$9.60", x0), "coral", "cost")
        self.assertRegex(self.box(self.rows(), "beta · 1 session")[1][1], r"\$?\? today")

    def test_line_two_shows_the_24h_sparkline_and_the_last_hour(self):
        row, text, x0 = self.box(self.rows(), "alpha · 3 sessions")[2]
        spark = self.r.sparkline(render_messages()["hourly"])
        self.assertInOrder(text, "24h ", spark, "7/h")
        # The first count is zero, a faint dot; the second is the first bar.
        self.assertWord(colour_of(row, spark[1:], x0), "blue", "sparkline")
        self.assertIn("24h ?", self.box(self.rows(), "beta · 1 session")[2][1])

    def test_a_session_row_shows_glyph_name_age_context_cost_and_one_badge(self):
        box = self.box(self.rows(), "alpha · 3 sessions")
        cases = {"Orc-Alpha": ("◐", "sky", ("10m", "42%", "$3.20")),
                 "Coord-a": ("■", "salmon", ("3m", "85%", "$3.20", "blocked")),
                 "Coord-b": ("○", "dim", ("1m", "60%", "$3.20", "typing"))}
        for name, (glyph, colour, facts) in cases.items():
            row, text, x0 = self.line(box, name)
            self.assertInOrder(text, glyph, name, *facts)
            self.assertWord(colour_of(row, glyph, x0), colour, name)
        row, text, x0 = self.line(self.box(self.rows(), "beta · 1 session"), "Kong")
        self.assertWord(colour_of(row, "?", x0), "amber", "unknown state")

    def test_working_done_and_ended_glyphs(self):
        for status, glyph, colour in (("working", "●", "green"), ("done", "✓", "green"), ("absent", "·", "faint")):
            snap = copy.deepcopy(self.snap)
            orc = a_session(snap, "Orc-Alpha")
            orc["herdr"]["status"] = status
            orc["flags"]["between_turns"] = False
            row, text, x0 = self.line(self.box(self.rows(snap), "alpha · 3 sessions"), "Orc-Alpha")
            self.assertLess(text.index(glyph), text.index("Orc-Alpha"), status)
            self.assertWord(colour_of(row, glyph, x0), colour, status)

    def test_the_context_bar_takes_the_heat_colour(self):
        box = self.box(self.rows(), "alpha · 3 sessions")
        for name, colour in (("Orc-Alpha", "orange"), ("Coord-b", "salmon"), ("Coord-a", "salmon")):
            row, text, x0 = self.line(box, name)
            self.assertWord(colour_of(row, "█", x0), colour, name)

    def test_one_badge_the_first_that_applies(self):
        def child_done(s):
            s["flags"].update(waiting_on_finished_child=True, typing=True)
            s["draft_since"] = NOW - 5

        def held(s):
            s["flags"]["held"] = True
            s["mail"].update(waiting=2, held=2, oldest_waiting_s=300)

        def api_error(s):
            s["flags"]["api_error"] = True
            s.update(api_error="overloaded", idle_exit_in_s=18000)

        def mail(s):
            s["mail"].update(waiting=1, held=0, oldest_waiting_s=120)

        def idle_exit(s):
            s["idle_exit_in_s"] = 18000

        cases = (("child done", child_done, " child done ", ("salmon", "bold"), ("typing",)),
                 ("held", held, "held 2", ("salmon",), ("✉2",)),
                 ("api error", api_error, "api error", ("amber",), ("exit",)),
                 ("mail", mail, "✉1 2m", ("amber",), ()),
                 ("exit", idle_exit, "exit 5h", ("faint",), ()))
        for name, change, badge, colours, absent in cases:
            with self.subTest(name):
                snap = copy.deepcopy(self.snap)
                change(a_session(snap, "Orc-Alpha"))
                row, text, x0 = self.line(self.box(self.rows(snap), "alpha · 3 sessions"), "Orc-Alpha")
                self.assertIn(badge, text)
                for colour in colours:
                    self.assertWord(colour_of(row, badge, x0), colour, name)
                for other in absent:
                    self.assertNotIn(other, text)
        box = self.box(self.rows(), "alpha · 3 sessions")
        row, text, x0 = self.line(box, "Coord-a")
        self.assertWord(colour_of(row, "blocked", x0), "salmon", "blocked")
        self.assertWord(colour_of(row, "blocked", x0), "bold", "blocked")
        self.assertNotIn("held", text)
        row, text, x0 = self.line(box, "Coord-b")
        self.assertWord(colour_of(row, "typing", x0), "amber", "typing")
        self.assertNotIn("api error", text)
        self.assertNotIn("exit", text)

    def test_the_cursor_row_is_marked_and_its_name_bold(self):
        rows = self.rows(cursor=1)
        box = self.box(rows, "alpha · 3 sessions")
        row, text, x0 = self.line(box, "Coord-a")
        self.assertIn("▸", text)
        self.assertWord(colour_of(row, "▸", x0), "coral", "cursor")
        self.assertWord(colour_of(row, "▸", x0), "bold", "cursor")
        self.assertWord(colour_of(row, "Coord-a", x0), "bold", "cursor name")
        others = [t for _, t, _ in box if "▸" in t] + [t for _, t, _ in self.box(rows, "beta · 1 session") if "▸" in t]
        self.assertEqual(len(others), 1, others)

    def test_a_session_row_has_no_model_effort_or_cache(self):
        for box_title, names in (("alpha · 3 sessions", ("Orc-Alpha", "Coord-a", "Coord-b")),
                                 ("beta · 1 session", ("Kong",))):
            box = self.box(self.rows(), box_title)
            for name in names:
                text = self.line(box, name)[1]
                for word in ("Opus", "Sonnet", "opus", "sonnet", "high", "max", "◆", "◇", "cache", "warm", "cold"):
                    self.assertNotIn(word, text, name)

    def test_the_role_is_the_name_colour_not_a_word_in_the_row(self):
        for box_title, name, colour in (("alpha · 3 sessions", "Orc-Alpha", "coral"),
                                        ("alpha · 3 sessions", "Coord-a", "blue"),
                                        ("beta · 1 session", "Kong", "teal")):
            row, text, x0 = self.line(self.box(self.rows(cursor=2), box_title), name)
            self.assertWord(colour_of(row, name, x0), colour, name)
            self.assertNotRegex(text, r"\b(orc|lane|guard)\b")
        snap = copy.deepcopy(self.snap)
        a_session(snap, "Coord-b")["role"] = "builder"
        row, text, x0 = self.line(self.box(self.rows(snap), "alpha · 3 sessions"), "Coord-b")
        self.assertWord(colour_of(row, "Coord-b", x0), "dim", "crew")


class RenderHaltedTests(RenderCase):
    """The halted box: one line per team that is not up."""

    def test_each_team_that_is_not_up_has_a_line(self):
        box = self.box(self.rows(), "halted")
        self.assertWord(colour_of(box[0][0], "halted", box[0][2]), "dim", "title")
        self.assertWord(colour_of(box[0][0], "halted", box[0][2]), "bold", "title")
        row, text, x0 = self.line(box, "beta")
        self.assertInOrder(text, "■ beta", "down", "loop off never started")
        self.assertWord(colour_of(row, "■", x0), "salmon", "glyph")
        row, text, x0 = self.line(box, "gamma")
        self.assertInOrder(text, "■ gamma", "halted", "loop off 2h14m", "✉ 3 waiting")
        self.assertWord(colour_of(row, "✉ 3 waiting", x0), "amber", "mail")
        self.assertNotIn("alpha", "\n".join(t for _, t, _ in box))

    def halted_with_sessions(self):
        """render_snapshot with HALTED gamma holding two sessions, one with a subagent (Q-21)."""
        snap = copy.deepcopy(self.snap)
        a_team(snap, "gamma")["sessions"] = [
            render_session("gamma", "orc", "Orc-Gamma", "orc"),
            render_session("gamma", "g", "Coord-g", "lane", agents=[render_agent("g1", description="gjob")])]
        return snap

    def test_a_halted_team_with_sessions_has_no_box_and_no_visible_sessions(self):
        snap = self.halted_with_sessions()
        ids = [sid for sid, _, _ in self.r.visible(snap)]
        self.assertEqual(ids, ["alpha/orc", "alpha/a", "alpha/b", "beta/kong"])
        screen = self.screen(snap)
        self.assertNotIn("gamma · 2 sessions", screen)
        row, text, x0 = self.line(self.box(self.rows(snap), "halted"), "gamma")
        self.assertInOrder(text, "■ gamma", "halted")

    def test_the_cursor_never_lands_on_a_halted_teams_session(self):
        snap = self.halted_with_sessions()
        last = len(self.r.visible(snap)) - 1
        for cursor in (0, last - 1, last, last + 1, last + 5):
            for all_agents in (False, True):
                with self.subTest(cursor=cursor, all_agents=all_agents):
                    texts = self.texts(snap, cursor=cursor, all_agents=all_agents)
                    screen = "\n".join(texts)
                    for name in ("Orc-Gamma", "Coord-g", "gjob"):
                        self.assertNotIn(name, screen)
                    marked = [t for t in texts if "▸" in t]
                    self.assertEqual(len(marked), 1, marked)
                    self.assertNotIn("Gamma", marked[0])

    def test_all_agents_lists_none_of_a_halted_teams_agents(self):
        screen = self.screen(self.halted_with_sessions(), all_agents=True)
        self.assertIn("2 total", screen)

    def test_a_down_team_with_sessions_keeps_its_box_and_visible_sessions(self):
        snap = self.halted_with_sessions()
        self.assertIn("beta/kong", [sid for sid, _, _ in self.r.visible(snap)])
        row, text, x0 = self.box(self.rows(snap), "beta · 1 session")[0]
        self.assertIn("down", text)
        self.assertIn("Kong", self.box_text(self.rows(snap, cursor=3), "beta · 1 session"))


class RenderFocusTests(RenderCase):
    """The focus box: the cursor's session, every SPEC-deck per-session field."""

    def focus(self, name, model="Opus 5.5", **kwargs):
        rows = self.rows(cursor=CURSOR[name], **kwargs)
        return rows, self.box(rows, f"{model} · {name}")

    def test_an_orc_between_turns(self):
        rows, box = self.focus("Orc-Alpha")
        top, text, x0 = box[0]
        self.assertWord(colour_at(top, x0), "coral", "border")
        self.assertWord(colour_of(top, "Opus 5.5", x0), "coral", "title")
        self.assertWord(colour_of(top, "Opus 5.5", x0), "bold", "title")
        self.assertInOrder(text, "Orc-Alpha", "◐ between 10m")
        body = "\n".join(t for _, t, _ in box)
        self.assertIn("effort ▮▮▮▯▯ high", body)
        row, line, x = self.line(box, "role orc")
        self.assertIn("role orc · alpha", line)
        self.assertWord(colour_of(row, "orc", x + line.index("role ")), "coral", "role")
        self.assertInOrder(self.line(box, "ctx")[1], "ctx", "42%", "420k/1.0M", "⟲2")
        self.assertInOrder(self.line(box, "session")[1], "$3.20 session", "$10.10 seat today")
        row, line, x = self.line(box, "cache")
        self.assertInOrder(line, "◆ warm", "20m left", "hit 90%")
        self.assertWord(colour_of(row, "◆", x), "purple", "warm cache")
        self.assertInOrder(self.line(box, "mail")[1], "✉ 0 waiting", "↓4 today", "oldest –")
        self.assertIn("flags none", body)

    def test_a_blocked_lane_with_held_mail(self):
        rows, box = self.focus("Coord-a")
        self.assertIn("■ blocked 3m", box[0][1])
        body = "\n".join(t for _, t, _ in box)
        self.assertIn("role lane · alpha", body)
        self.assertIn("85%", self.line(box, "ctx")[1])
        row, line, x = self.line(box, "mail")
        self.assertInOrder(line, "✉ 2 waiting", "↓4 today", "oldest 5m", "held 2")
        self.assertWord(colour_of(row, "held 2", x), "salmon", "held")
        self.assertWord(colour_of(row, "held 2", x), "bold", "held")
        self.assertIn("blocked 3m", self.line(box, "flags")[1])

    def test_an_idle_lane_typing_with_an_api_error_and_an_idle_exit(self):
        rows, box = self.focus("Coord-b", model="Sonnet 4.6")
        self.assertIn("○ idle 1m", box[0][1])
        body = "\n".join(t for _, t, _ in box)
        self.assertIn("effort ▮▮▮▮▮ max", body)
        self.assertIn("◇ cold", body)
        self.assertIn("$10.10+ seat today", body)
        self.assertIn("⟲2+", body)
        self.assertInOrder(self.line(box, "flags")[1], "typing", "api error", "exit 5h")

    def test_every_flag_and_held_mail_show_whole_in_the_focus_box(self):
        snap = copy.deepcopy(self.snap)
        s = a_session(snap, "Coord-a")
        s["flags"].update(waiting_on_finished_child=True, typing=True, api_error=True)
        s.update(draft_since=NOW - 20, api_error="overloaded", idle_exit_in_s=18000)
        rows = self.rows(snap, cursor=CURSOR["Coord-a"])
        self.assertEqual(broken_boxes([row_text(r) for r in rows]), [])
        body = [text for _, text, _ in self.box(rows, "Opus 5.5 · Coord-a")[1:-1]]
        for word in ("child done", "blocked 3m", "typing", "api error", "exit 5h", "held 2"):
            with self.subTest(word=word):
                found = [line for line in body if word in line]
                self.assertTrue(found, f"{word!r} not in the focus box: {body}")
                self.assertNotIn("…", found[0], word)

    def test_unknown_fields_show_a_question_mark(self):
        rows, box = self.focus("Kong", model="?")
        body = "\n".join(t for _, t, _ in box)
        self.assertIn("effort ▯▯▯▯▯ ?", body)
        row, line, x = self.line(box, "role guard")
        self.assertIn("role guard · beta", line)
        self.assertWord(colour_of(row, "guard", x + line.index("role ")), "teal", "role")
        self.assertIn("?", self.line(box, "ctx")[1])
        self.assertIn("?", self.line(box, "session")[1])

    def test_a_model_name_is_shortened(self):
        snap = copy.deepcopy(self.snap)
        a_session(snap, "Orc-Alpha")["model"] = "claude-haiku-4-5-20251001"
        texts = self.texts(snap)
        find_box(texts, "haiku-4-5-20 · Orc-Alpha")
        self.assertNotIn("claude-", "\n".join(texts))

    def test_expanded_adds_the_recent_tools_and_messages(self):
        right = [t[LEFT_120 + 1:] for t in self.texts(cursor=0, expanded={"alpha/orc"})]
        tool = [t for t in right if "tool" in t and "render.py" in t]
        self.assertEqual(len(tool), 1, right)
        self.assertInOrder(tool[0], "tool", "Read", "render.py")
        msg = [t for t in right if "msg" in t and "look again" in t]
        self.assertEqual(len(msg), 1, right)
        self.assertInOrder(msg[0], "msg", "→", hhmm(NOW - 120), "Coord-a", "REQUEST", "look again")
        self.assertNotIn("render.py", self.screen(cursor=0))
        self.assertIn("nothing recent", self.screen(cursor=2, expanded={"alpha/b"}))

    def test_an_expanded_id_away_from_the_cursor_has_no_effect(self):
        self.assertNotIn("render.py", self.screen(cursor=1, expanded={"alpha/orc"}))


class RenderAgentsTests(RenderCase):
    """The agents lines under the focus box: the cursor session's subagents, or every session's with all_agents."""

    def right(self, **kwargs):
        rows = self.rows(**kwargs)
        return rows, [row_text(r)[LEFT_120 + 1:] for r in rows]

    def one(self, texts, needle):
        found = [n for n, t in enumerate(texts) if needle in t]
        self.assertEqual(len(found), 1, f"{needle!r}: {texts}")
        return found[0]

    def test_the_header_counts_running_and_total(self):
        rows, right = self.right(cursor=1)
        n = self.one(right, "agents · ")
        self.assertInOrder(right[n], "agents · 1 running · 2 total", "⏎ expand")
        self.assertWord(colour_of(rows[n], "⏎ expand", LEFT_120 + 1), "faint", "expand")

    def test_rows_by_start_with_mark_number_description_lane_and_timer(self):
        rows, right = self.right(cursor=1)
        done, running = self.one(right, "1: baseline"), self.one(right, "2: port")
        self.assertLess(done, running)
        self.assertRegex(right[done], r"✓ 1: baseline tests")
        self.assertIn("3:20", right[done])
        self.assertRegex(right[running], r"●   2: port")
        self.assertIn("…", right[running])
        self.assertNotIn("failing tests", right[running])
        self.assertIn("15:00", right[running])
        self.assertWord(colour_of(rows[done], "✓", LEFT_120 + 1), "green", "finished")
        self.assertWord(colour_of(rows[running], "●", LEFT_120 + 1), "blue", "running")
        self.assertWord(colour_of(rows[running], "━", LEFT_120 + 1), "blue", "lane")
        self.assertWord(colour_of(rows[running], "·", LEFT_120 + 1), "faint", "track")

    def test_a_stalled_agent_and_the_other_badges(self):
        cases = (("stalled", "stalled", "salmon"), ("waiting_on_finished_child", "waits on finished child", "salmon"),
                 ("orphan", "orphan", "amber"))
        for flag, badge, colour in cases:
            with self.subTest(flag):
                snap = copy.deepcopy(self.snap)
                a_session(snap, "Coord-a")["agents"][0]["flags"][flag] = True
                rows, right = self.right(snap=snap, cursor=1)
                n = self.one(right, "2: port")
                self.assertIn(badge, right[n])
                self.assertWord(colour_of(rows[n], badge, LEFT_120 + 1 + right[n].index("2: port")), colour, badge)
                if flag == "stalled":
                    self.assertWord(colour_of(rows[n], "■", LEFT_120 + 1), "salmon", "stalled mark")

    def test_expanded_adds_type_tokens_and_last_write(self):
        rows, right = self.right(cursor=1, expanded={"alpha/a"})
        detail = [t for t in right if "coder" in t]
        self.assertEqual(len(detail), 1, right)
        self.assertInOrder(detail[0], "coder", "token", "last write 40s ago")
        self.assertTrue("12345" in detail[0] or "12.3k" in detail[0], detail[0])
        self.assertIn("last write 16m ago", "\n".join(right))
        self.assertNotIn("last write", self.screen(cursor=1))

    def lane_columns(self, right, needle):
        """(first track cell, first ━, last ━) of the one agent row holding needle, in right-column columns."""
        text = right[self.one(right, needle)]
        at = text.index(needle)
        start = min(text.index(c, at) for c in "·━" if c in text[at:])
        return start, text.index("━", at), text.rindex("━")

    def badged(self):
        """Coord-a's agents plus a3: a3 starts and last writes when a1 does and carries two badges."""
        snap = copy.deepcopy(self.snap)
        a_session(snap, "Coord-a")["agents"].append(render_agent(
            "a3", description="badged twin", depth=1,
            flags={"stalled": False, "waiting_on_finished_child": True, "orphan": True}))
        return snap

    def test_every_lane_starts_at_one_column_with_or_without_badges(self):
        rows, right = self.right(snap=self.badged(), cursor=1)
        starts = {needle: self.lane_columns(right, needle)[0] for needle in ("1: basel", "2: port", "3: badge")}
        self.assertIn("waits on finished child", right[self.one(right, "3: badge")])
        self.assertEqual(len(set(starts.values())), 1, f"{starts}\n" + "\n".join(right))

    def test_equal_times_map_to_the_same_lane_columns(self):
        rows, right = self.right(snap=self.badged(), cursor=1)
        plain, badged = self.lane_columns(right, "2: port"), self.lane_columns(right, "3: badge")
        self.assertEqual(plain, badged, "\n".join(right))

    def test_with_all_agents_every_lane_starts_at_one_column(self):
        snap = copy.deepcopy(self.snap)
        a_session(snap, "Orc-Alpha")["agents"] = [render_agent("o1", description="read the spec", depth=1,
                                                               started=NOW - 500)]
        a_session(snap, "Coord-a")["agents"][0]["flags"]["stalled"] = True
        rows, right = self.right(snap=snap, cursor=0, all_agents=True)
        starts = {needle: self.lane_columns(right, needle)[0]
                  for needle in (": basel", ": port", ": read")}
        self.assertEqual(len(set(starts.values())), 1, f"{starts}\n" + "\n".join(right))

    def test_all_agents_lists_every_sessions_agents_with_the_session_name(self):
        rows, right = self.right(cursor=0, all_agents=True)
        self.assertIn("all sessions", right[self.one(right, "agents · ")])
        n = self.one(right, "2: port")
        self.assertWord(colour_of(rows[n], "Coord-a", LEFT_120 + 1 + right[n].index("2: port")), "dim", "session")
        self.assertNotIn("agents · ", self.screen(cursor=0))


_AGENT_ROW = re.compile(r"^[✓■●] (\d+): (task-\d+)")
_MORE_ROW = re.compile(r"^\s*\+(\d+) more\s*$")


def many_agents(sessions, total):
    """tall_snapshot with `total` running depth-1 agents dealt round the named alpha sessions; agent g (0-based)
    starts g * 10 s after the first and is described `task-<g+1>`, so start order is task order."""
    snap = tall_snapshot()
    for name in sessions:
        a_session(snap, name)["agents"] = []
    for g in range(total):
        a_session(snap, sessions[g % len(sessions)])["agents"].append(render_agent(
            f"g{g}", description=f"task-{g + 1:02d}", depth=1, started=NOW - 3000 + 10 * g))
    return snap


class RenderAgentsCutTests(RenderCase):
    """Rework 3, T2: an unboxed agents list taller than the room shows its header, its first rows in order and a
    last `+n more` row counting the rest; it is dropped only when not even those two rows fit. Boxes stay whole."""

    ALL = ("Orc-Alpha", "Coord-a", "Coord-b")

    def column(self, rows, width):
        """The middle region's rows of the column the dock is in: the right column at 120, the one column below."""
        texts = middle_rows([row_text(row) for row in rows])
        return [t[LEFT_120 + 1:] for t in texts] if width >= 120 else texts

    def cut_faults(self, rows, width, height, total):
        """What breaks T2 on one screen whose agents list cannot fit: the header, the first rows 1..k in order, a
        last `+n more` with n = total - k, rows <= height, the `▸` row on screen, no box cut open."""
        texts, column = [row_text(row) for row in rows], self.column(rows, width)
        heads = [y for y, t in enumerate(column) if "agents · " in t]
        if len(heads) != 1:
            return [f"{len(heads)} agents headers"]
        listed = column[heads[0] + 1:]
        shown = [m.groups() for m in map(_AGENT_ROW.match, (t.strip() for t in listed)) if m]
        faults = [] if len(texts) <= height else [f"{len(texts)} rows"]
        if [n for n, _ in shown] != [str(i) for i in range(1, len(shown) + 1)] or \
                [d for _, d in shown] != [f"task-{i:02d}" for i in range(1, len(shown) + 1)]:
            faults.append(f"not the first rows in order: {shown}")
        more = _MORE_ROW.match(listed[len(shown)]) if len(listed) > len(shown) else None
        if more is None or int(more[1]) != total - len(shown):
            faults.append(f"after {len(shown)} rows, not `+{total - len(shown)} more`: {listed[len(shown):][:1]}")
        if len([t for t in texts if "▸" in t]) != 1:
            faults.append("no `▸` row")
        focus = coral_box(rows)
        if focus is not None and not focus[1]:
            faults.append("the focus box is cut open")
        boxed = column if width >= 120 else texts[texts.index(next(t for t in texts if "agents · " in t)):]
        return faults + broken_boxes(boxed)

    def test_one_sessions_long_list_at_120_shows_its_first_rows_and_counts_the_rest(self):
        self.check_120(many_agents(("Coord-a",), 40), cursor=1, total=40)

    def test_all_agents_long_list_at_120_shows_its_first_rows_and_counts_the_rest(self):
        self.check_120(many_agents(self.ALL, 42), cursor=0, total=42, all_agents=True)

    def check_120(self, snap, cursor, total, **kwargs):
        """Every height 20..50 at 120: where the room under the focus box (and its gap) holds at least 2 rows the
        list is cut as T2 says and fills that room; where it holds fewer the list is absent."""
        bad = {}
        for height in range(20, 51):
            rows = self.rows(snap, 120, cursor=cursor, height=height, **kwargs)
            column, focus = self.column(rows, 120), coral_box(rows)
            room = len(column) - (len(focus[0]) + 1 if focus else 0)
            if room < 2:
                faults = [t for t in column if "agents · " in t]
            else:
                faults = self.cut_faults(rows, 120, height, total)
                if not faults and not _MORE_ROW.match(column[-1]):
                    faults = [f"the list does not fill the {room} rows under the focus box"]
            if faults:
                bad[height] = faults
        self.assertEqual(bad, {})

    def test_long_lists_under_120_with_a_height_show_their_first_rows_and_count_the_rest(self):
        cases = ((many_agents(("Coord-a",), 40), 1, 40, {}), (many_agents(self.ALL, 42), 0, 42, {"all_agents": True}))
        for snap, cursor, total, kwargs in cases:
            for height in (30, 40, 50):
                rows = self.rows(snap, 80, cursor=cursor, height=height, **kwargs)
                with self.subTest(total=total, height=height):
                    self.assertEqual(self.cut_faults(rows, 80, height, total), [])

    def test_a_list_with_room_shows_whole_without_more(self):
        for width in (120, 80):
            for kwargs in ({"cursor": 1}, {"cursor": 0, "all_agents": True}):
                snap = many_agents(("Coord-a",) if "all_agents" not in kwargs else self.ALL, 5)
                column = self.column(self.rows(snap, width, height=60, **kwargs), width)
                shown = [m[2] for m in map(_AGENT_ROW.match, (t.strip() for t in column)) if m]
                with self.subTest(width=width, **kwargs):
                    self.assertEqual(shown, [f"task-{i:02d}" for i in range(1, 6)], column)
                    self.assertEqual([t for t in column if _MORE_ROW.match(t)], [])


class RenderLogTests(RenderCase):
    """The log box: the cursor's team's last messages."""

    def test_the_title_and_the_counts_at_its_right(self):
        row, text, x0 = self.box(self.rows(), "log · alpha")[0]
        self.assertInOrder(text, "log · alpha", "↓9", "held 2", "queued 2", "bcast 1")
        self.assertWord(colour_of(row, "held 2", x0), "salmon", "held")

    def test_a_message_row_shows_time_sender_recipient_and_kind(self):
        row, text, x0 = self.line(self.box(self.rows(), "log · alpha"), "REQUEST")
        self.assertInOrder(text, hhmm(NOW - 60, secs=True), "Orc-Alpha", "→", "Coord-a", "REQUEST")
        self.assertRegex(text, r"→\s*Coord-a")
        self.assertWord(colour_of(row, hhmm(NOW - 60, secs=True), x0), "faint", "time")
        self.assertWord(colour_of(row, "Orc-Alpha", x0), "coral", "sender")
        self.assertWord(colour_of(row, "Coord-a", x0), "blue", "recipient")
        self.assertWord(colour_of(row, "REQUEST", x0), "amber", "kind")
        self.assertWord(colour_of(row, "REQUEST", x0), "bold", "kind")

    def test_a_name_that_is_not_a_session_of_the_team_is_dim(self):
        row, text, x0 = self.line(self.box(self.rows(), "log · alpha"), "Stranger")
        self.assertInOrder(text, "Stranger", "→", "all", "NOTE")
        self.assertWord(colour_of(row, "Stranger", x0), "dim", "sender")
        self.assertWord(colour_of(row, "NOTE", x0), "purple", "kind")

    def test_the_top_senders_and_recipients(self):
        box = self.box(self.rows(), "log · alpha")
        self.assertInOrder(self.line(box, "from")[1], "from", "Orc-Alpha 5", "Coord-a 3")
        self.assertInOrder(self.line(box, "Coord-a 4")[1], "to", "Coord-a 4")

    def test_the_log_follows_the_cursors_team(self):
        texts = self.texts(cursor=3)
        rows = self.rows(cursor=3)
        row, text, x0 = self.line(self.box(rows, "log · beta"), "messages ?")
        self.assertWord(colour_of(row, "messages ?", x0), "amber", "unknown messages")
        self.assertNotIn("log · alpha", "\n".join(texts))

    def test_a_v1_team_has_no_log(self):
        snap = copy.deepcopy(self.snap)
        a_team(snap, "beta")["state"] = "v1"
        find_box(self.texts(snap, cursor=0), "log · alpha")
        self.assertNotIn("log · ", self.screen(snap, cursor=3))


class RenderDiskTests(RenderCase):
    """The DISK box: teams largest first, their worktrees with build parts, and the largest build folders."""

    def test_the_title_and_the_free_space_and_scan_age(self):
        row, text, x0 = self.box(self.rows(), "DISK")[0]
        self.assertInOrder(text, "DISK", "300G free", "10m ago")
        self.assertWord(colour_of(row, "DISK", x0), "blue", "title")
        self.assertWord(colour_of(row, "DISK", x0), "bold", "title")

    def test_teams_largest_first_with_their_size(self):
        box = self.box(self.rows(), "DISK")
        text = "\n".join(t for _, t, _ in box)
        self.assertInOrder(text, "gamma", "95.0G", "alpha", "80.0G")
        self.assertIn("▕" + "█" * 12 + "▏", self.line(box, "gamma")[1])

    def test_worktrees_with_their_parts_and_build_output_over_the_line_is_salmon(self):
        box = self.box(self.rows(), "DISK")
        row, text, x0 = self.line(box, "cargo-target 12.0G")
        self.assertIn("40.0G", text)
        self.assertWord(colour_of(row, "cargo-target 12.0G", x0), "salmon", "over the line")
        row, text, x0 = self.line(box, "target 2.0G")
        self.assertIn("6.0G", text)
        self.assertFalse(has(colour_of(row, "target 2.0G", x0), "salmon"), text)

    def test_the_largest_build_folders_move_here_dim(self):
        row, text, x0 = self.line(self.box(self.rows(), "DISK"), "largest")
        self.assertInOrder(text, "largest", "12.0G", "cargo-target")
        self.assertWord(colour_of(row, "largest", x0), "dim", "largest")

    def test_low_free_space_is_salmon(self):
        snap = copy.deepcopy(self.snap)
        snap["volume"]["free_gb"] = 30.0
        row, text, x0 = self.box(self.rows(snap), "DISK")[0]
        self.assertWord(colour_of(row, "30", x0), "salmon", "free < 50 GB")

    def test_every_build_part_shows_whole_largest_first_on_its_worktrees_rows_at_every_width(self):
        # Rework 3, T1: together the six parts are far wider than any body, so they wrap onto continuation rows.
        snap = copy.deepcopy(self.snap)
        a_team(snap, "alpha")["disk"]["worktrees"] = [
            {"path": "/t/alpha/wt-all-parts", "size_gb": 4000.0, "parts": dict(WRAP_PARTS)},
            {"path": "/t/alpha/wt-other", "size_gb": 6.0, "parts": {"target": 2.0}}]
        expected = [f"{p} {WRAP_PARTS[p]:.1f}G" for p in sorted(WRAP_PARTS, key=lambda p: -WRAP_PARTS[p])]
        for width in (120, 80, 30):
            body = (53 if width >= 120 else width) - 4
            bodies = box_bodies(self.texts(snap, width), "DISK")
            blocks = disk_blocks(bodies)
            with self.subTest(width=width):
                self.assertEqual([b for b in bodies if re.search(r"\+\d", b)], [], "no +n on the DISK rows")
                self.assertIn("wt-all-parts", blocks, bodies)
                head, shown = blocks["wt-all-parts"]
                self.assertEqual(head, "4000.0G", bodies)
                self.assertEqual(shown, [item for item in expected if len(item) <= body - 2], bodies)
                self.assertEqual(blocks.get("wt-other"), ("6.0G", ["target 2.0G"]), bodies)


class RenderAlertsTests(RenderCase):
    """The ALERTS box: newest first, red kinds salmon, at most ALERT_ROWS with a height."""

    def log(self, n):
        return [{"key": f"over_cap:t{i}:cap", "kind": "over_cap", "team": f"t{i}", "session": None,
                 "text": f"alert number {i}", "since": NOW - i} for i in range(n)]

    def test_each_alert_line_and_the_box_colours(self):
        box = self.box(self.rows(), "ALERTS")
        top, text, x0 = box[0]
        self.assertIn("newest first", text)
        self.assertWord(colour_at(top, x0), "amber", "border")
        row, line, x = self.line(box, "build output")
        self.assertInOrder(line, "▲", hhmm(NOW - 60), "alpha", "/t/alpha/wt build output 12.0 GB")
        self.assertWord(colour_of(row, "▲", x), "amber", "warning")
        self.assertWord(colour_of(row, hhmm(NOW - 60), x), "faint", "time")
        self.assertWord(colour_of(row, "alpha", x), "dim", "team")
        self.assertWord(colour_of(row, "/t/alpha", x), "amber", "text")
        row, line, x = self.line(box, "blocked for 3 min")
        self.assertInOrder(line, "▲", hhmm(NOW - 180), "alpha", "Coord-a blocked")
        self.assertWord(colour_of(row, "▲", x), "salmon", "red kind")
        self.assertWord(colour_of(row, "Coord-a blocked", x), "salmon", "red kind text")
        self.assertLess(box.index(self.line(box, "build output")), box.index(self.line(box, "blocked for 3 min")))

    def test_with_a_height_at_most_alert_rows_and_the_rest_counted(self):
        box = self.box(self.rows(alert_log=self.log(9), height=40), "ALERTS")
        self.assertEqual(sum("▲" in t for _, t, _ in box), self.r.ALERT_ROWS)
        self.assertIn("+3 more", box[0][1])
        whole = self.box(self.rows(alert_log=self.log(9)), "ALERTS")
        self.assertEqual(sum("▲" in t for _, t, _ in whole), 9)


class RenderLayoutTests(RenderCase):
    """Columns by width, the cursor's team first, and pinning with a height."""

    def test_two_columns_at_120(self):
        texts = self.texts()
        self.assertTrue([t for t in texts if "alpha · 3 sessions" in t and "Opus 5.5 · Orc-Alpha" in t], texts)
        self.assertEqual(find_box(texts, "alpha · 3 sessions")[1:], (0, LEFT_120 - 1))
        self.assertEqual(find_box(texts, "Opus 5.5 · Orc-Alpha")[1:], (LEFT_120 + 1, 119))

    def test_team_boxes_go_two_across_at_180(self):
        texts = self.texts(width=180)
        left = 180 - 54
        self.assertTrue([t for t in texts if "alpha · 3 sessions" in t and "beta · 1 session" in t], texts)
        _, x0, x1 = find_box(texts, "alpha · 3 sessions")
        self.assertEqual(x1 - x0 + 1, (left - 1) // 2)
        _, x0, x1 = find_box(texts, "halted")
        self.assertEqual((x0, x1), (0, left - 1))
        _, x0, x1 = find_box(texts, "Opus 5.5 · Orc-Alpha")
        self.assertEqual((x0, x1), (left + 1, 179))

    def test_one_column_under_120(self):
        texts = self.texts(width=80)
        self.assertFalse([t for t in texts if "alpha · 3 sessions" in t and "Opus 5.5" in t])
        focus = find_box(texts, "Opus 5.5 · Orc-Alpha")
        self.assertEqual(focus[1:], (0, 79))
        for title in ("alpha · 3 sessions", "beta · 1 session", "halted"):
            y, x0, x1 = find_box(texts, title)
            self.assertLess(y, focus[0], title)
            self.assertEqual((x0, x1), (0, 79), title)

    def test_the_cursors_team_box_comes_first_with_a_blue_border(self):
        for cursor, first, second in ((0, "alpha · 3 sessions", "beta · 1 session"),
                                      (3, "beta · 1 session", "alpha · 3 sessions")):
            with self.subTest(cursor=cursor):
                rows = self.rows(cursor=cursor)
                texts = [row_text(r) for r in rows]
                y1, x1, _ = find_box(texts, first)
                y2, x2, _ = find_box(texts, second)
                self.assertLess(y1, y2)
                self.assertWord(colour_at(rows[y1], x1), "blue", "cursor's team")
                self.assertWord(colour_at(rows[y2], x2), "edge", "other team")

    def pinned(self, width, height):
        snap = tall_snapshot()
        cursor = len(self.r.visible(snap)) - 1
        return self.texts(snap, width, cursor=cursor, height=height)

    def test_pinning_at_height_40_keeps_the_top_the_alerts_the_keys_and_the_cursor_row(self):
        for width in (120, 80):
            with self.subTest(width=width):
                texts = self.pinned(width, 40)
                self.assertLessEqual(len(texts), 40)
                self.assertIn("CODETEAM DECK", texts[0])
                self.assertEqual(texts[-1].strip(), KEY_LINE)
                fleet = "\n".join(texts[:12])
                for name in ("alpha", "beta", "gamma", "delta"):
                    self.assertIn(name, fleet)
                find_box(texts, "ALERTS")
                marked = [t for t in texts if "▸" in t]
                self.assertEqual(len(marked), 1, texts)
                self.assertIn("Coord-d29", marked[0])
        find_box(self.pinned(120, 40), "Opus 5.5 · Coord-d29")

    def deep(self, width, name, height=None):
        """tall_snapshot with the cursor on session `name` of delta (30 sessions)."""
        snap = tall_snapshot()
        cursor = [s["name"] for _, _, s in self.r.visible(snap)].index(name)
        return self.rows(snap, width, cursor=cursor, height=height)

    def assertFocusWhole(self, rows, name):
        """The focus box of `name` is on screen from its title to its bottom border, every field line in it."""
        box = self.box(rows, f"Opus 5.5 · {name}")
        texts = [text for _, text, _ in box]
        self.assertTrue(len(texts) > 1 and texts[-1].startswith("╰"), f"the focus box is cut: {texts}")
        for field in ("effort", "ctx", "session", "cache", "mail", "flags"):
            self.assertTrue([t for t in texts[1:-1] if field in t], f"{field!r} not in the focus box: {texts}")

    def test_under_120_with_a_height_the_focus_box_shows_with_the_cursor_row(self):
        for height in (30, 40):
            for name in ("Coord-d15", "Coord-d29"):
                with self.subTest(height=height, name=name):
                    rows = self.deep(80, name, height)
                    texts = [row_text(r) for r in rows]
                    self.assertLessEqual(len(texts), height)
                    marked = [t for t in texts if "▸" in t]
                    self.assertEqual(len(marked), 1, "\n".join(texts))
                    self.assertIn(name, marked[0])
                    self.assertFocusWhole(rows, name)

    def test_at_120_with_a_height_the_focus_box_shows_with_the_cursor_row(self):
        for name in ("Coord-d15", "Coord-d29"):
            with self.subTest(name=name):
                rows = self.deep(120, name, 40)
                self.assertLessEqual(len(rows), 40)
                self.assertIn(name, "".join(row_text(r) for r in rows if "▸" in row_text(r)))
                self.assertFocusWhole(rows, name)

    def test_without_a_height_one_column_keeps_the_focus_box_below_the_left_stack(self):
        texts = [row_text(r) for r in self.deep(80, "Coord-d15")]
        focus = find_box(texts, "Opus 5.5 · Coord-d15")[0]
        for title in ("delta · 30 sessions", "alpha · 3 sessions", "beta · 1 session", "halted"):
            self.assertLess(find_box(texts, title)[0], focus, title)

    def test_short_heights_never_give_more_rows_and_keep_the_header_and_key_line(self):
        for width in (120, 80):
            for height in (10, 5, 2):
                with self.subTest(width=width, height=height):
                    texts = self.pinned(width, height)
                    self.assertLessEqual(len(texts), height)
                    self.assertIn("CODETEAM DECK", texts[0])
                    self.assertEqual(texts[-1].strip(), KEY_LINE)
            for height in (1, 0):
                self.assertLessEqual(len(self.pinned(width, height)), height)


BUDGET_WIDTHS = (80, 120, 150, 180, 186, 240)


def box_bodies(texts, title):
    """The body text of each row of the box titled `title`, between `│ ` and ` │`, right spaces stripped."""
    y, x0, x1 = find_box(texts, title)
    out = []
    for text in texts[y + 1:]:
        if text[x0:x0 + 1] != "│":
            break
        out.append(text[x0 + 2:x1 - 1].rstrip())
    return out


def coral_box(rows):
    """The focus box (the one coral border) as (texts cut to the box, closed): its rows from the title down, and
    whether its bottom border is on screen. None when no coral top corner shows."""
    texts = [row_text(row) for row in rows]
    for y, (row, text) in enumerate(zip(rows, texts)):
        x0 = text.find("╭")
        while x0 >= 0 and not has(colour_at(row, x0), "coral"):
            x0 = text.find("╭", x0 + 1)
        if x0 < 0:
            continue
        x1 = text.index("╮", x0)
        box = [text[x0:x1 + 1]]
        for below in texts[y + 1:]:
            below = below.ljust(x1 + 1)
            box.append(below[x0:x1 + 1])
            if below[x0] == "╰" and below[x1] == "╯":
                return box, True
            if below[x0] != "│" or below[x1] != "│":
                break
        return box, False
    return None


class RenderBudgetTests(RenderCase):
    """The space budget (plan, Rework 2, S1-S2) on the worst case at every width: required fields whole, optional
    fields whole or absent, never cut mid-field. Each width's faults are listed in one assertion."""

    def setUp(self):
        super().setUp()
        self.stress = stress_snapshot()

    def stress_texts(self, width, cursor=0, **kwargs):
        return self.texts(self.stress, width, cursor=cursor, expanded={f"{STRESS_TEAM}/s1"}, **kwargs)

    def test_every_session_row_keeps_its_badge_age_context_and_cost_whole(self):
        for width in BUDGET_WIDTHS:
            texts, faults = self.stress_texts(width), []
            for n, badge in STRESS_BADGES.items():
                prefix = stress_name(n)[:11]
                found = [m.group() for m in (re.search(rf"│ [▸ ][●◐○✓·■?] {re.escape(prefix)}[^│]*", t) for t in texts)
                         if m]
                if len(found) != 1:
                    faults.append(f"{len(found)} team box rows for {prefix!r}")
                    continue
                faults += [f"{fact!r} cut in {found[0]!r}" for fact in (DAY, "100%", "$123.45", badge)
                           if fact not in found[0]]
            with self.subTest(width=width):
                self.assertEqual(faults, [])

    def test_a_running_job_keeps_pid_gone_and_its_timer_and_its_optional_fields_whole_or_absent(self):
        for width in BUDGET_WIDTHS:
            running = [b for b in box_bodies(self.stress_texts(width), "BUILDS") if b.startswith("● ")]
            gone = [b for b in running if "pid gone" in b]
            faults = [] if len(gone) == 1 and "23h59" in gone[0] else [f"pid gone and the timer, whole: {running}"]
            faults += [f"cut: {b!r}" for b in running if b.endswith("…")]
            faults += [f"cost cut: {b!r}" for b in running if "cost" in b and not re.search(r"cost \d+\.\d(\s|$)", b)]
            with self.subTest(width=width):
                self.assertEqual(len(running), 2, running)
                self.assertEqual(faults, [])

    def test_a_queued_job_keeps_its_position_hold_and_wait_and_its_optional_fields_whole_or_absent(self):
        start = rf"start ({re.escape(hhmm(NOW + 1800))}|\?)(\s|$)"
        for width in BUDGET_WIDTHS:
            bodies, faults = [b for b in box_bodies(self.stress_texts(width), "BUILDS") if b.startswith("#")], []
            for n in range(10, 22):
                found = [b for b in bodies if b.startswith(f"#{n} ")]
                if len(found) != 1:
                    faults.append(f"{len(found)} rows for #{n}")
                    continue
                body, hold = found[0], STRESS_HOLDS[n % 4]
                faults += [f"{fact!r} cut in {body!r}" for fact in ([f"held {hold}"] if hold else []) + [f"wait {DAY}"]
                           if fact not in body]
                if body.endswith("…") or ("start" in body and not re.search(start, body)):
                    faults.append(f"an optional field cut: {body!r}")
            with self.subTest(width=width):
                self.assertEqual(faults, [])

    def test_the_waits_row_keeps_med_and_max_whole(self):
        for width in BUDGET_WIDTHS:
            with self.subTest(width=width):
                waits = [b for b in box_bodies(self.stress_texts(width), "BUILDS") if b.startswith("waits")]
                self.assertEqual(waits, [f"waits 24h · full · 123 · med {DAY} · max {DAY}"])

    def test_the_focus_caption_keeps_the_state_word_and_age_for_every_cursor(self):
        for width in BUDGET_WIDTHS:
            faults = []
            for n, state in STRESS_STATE.items():
                found = coral_box(self.rows(self.stress, width, cursor=n - 1))
                if found is None or f"{state} {DAY}" not in found[0][0]:
                    faults.append(f"{state} {DAY} not whole in {found and found[0][0]!r}")
            with self.subTest(width=width):
                self.assertEqual(faults, [])

    def test_the_focus_first_line_keeps_effort_and_role_and_its_team_whole_or_absent(self):
        for width in BUDGET_WIDTHS:
            with self.subTest(width=width):
                box, _ = coral_box(self.rows(self.stress, width, cursor=0))
                lines = [line for line in box if "effort" in line]
                self.assertEqual(len(lines), 1, box)
                self.assertIn("effort ▮▮▮▮▯ xhigh", lines[0])
                self.assertIn("role designer", lines[0])
                self.assertNotIn("…", lines[0], "the team is optional: whole or absent")

    def test_the_team_box_caption_keeps_the_loop_age(self):
        for width in BUDGET_WIDTHS:
            texts = self.stress_texts(width)
            with self.subTest(width=width):
                self.assertEqual([age for age in (DAY, "5s") if not [t for t in texts if f"● up · loop {age}" in t]], [])

    def test_the_log_caption_keeps_held(self):
        caption = "↓123 held 123 queued 123 bcast 123"
        for width in BUDGET_WIDTHS:
            with self.subTest(width=width):
                self.assertTrue([t for t in self.stress_texts(width) if caption in t], f"{caption!r} cut")

    def test_a_halted_row_keeps_its_state_loop_and_mail_whole(self):
        for width in BUDGET_WIDTHS:
            bodies = box_bodies(self.stress_texts(width), "halted")
            for parts in (("halted", f"loop off {DAY}", "✉ 123 waiting"),
                          ("down", "loop off never started", "✉ 456 waiting")):
                with self.subTest(width=width, parts=parts):
                    found = [b for b in bodies if all(p in b for p in parts)]
                    self.assertEqual(len(found), 1, bodies)
                    self.assertInOrder(found[0], *parts)

    def test_every_disk_worktree_keeps_its_size_and_shows_every_build_part_whole_largest_first_on_its_rows(self):
        expected = {"234.5G": STRESS_PARTS, "6.0G": {"target": 2.0}}
        for width in BUDGET_WIDTHS:
            bodies = box_bodies(self.stress_texts(width), "DISK")
            text = "\n".join(bodies)
            faults = [f"{size!r} cut" for size in ("456.7G", "789.0G", "234.5G", "6.0G", "largest 111.1G")
                      if size not in text]
            faults += [f"+n on a DISK row: {b!r}" for b in bodies if re.search(r"\+\d", b)]
            blocks = disk_blocks(bodies)
            sizes = sorted(size for size, _ in blocks.values())
            if sizes != sorted(expected):
                faults.append(f"worktree rows {sizes}, not {sorted(expected)}")
            for size, shown in blocks.values():
                parts = expected.get(size, {})
                whole = [f"{p} {parts[p]:.1f}G" for p in sorted(parts, key=lambda p: -parts[p])]
                if shown != whole:
                    faults.append(f"the {size} worktree's parts, whole and largest first: {shown} not {whole}")
            with self.subTest(width=width):
                self.assertEqual(faults, [], "\n".join(bodies))

    def test_the_header_keeps_its_counts_whole_and_drops_the_clock_and_lanes_whole(self):
        # With a team filter the required fields alone take 90 cells, so that case starts at 120.
        cases = [(width, None) for width in BUDGET_WIDTHS] + [(width, STRESS_TEAM) for width in BUDGET_WIDTHS[1:]]
        for width, team_filter in cases:
            header = self.texts(self.stress, width, team_filter=team_filter)[0]
            required = ["CODETEAM DECK", "1 UP", "0 HALTED", "▲ 123 ALERTS", "123 source errors",
                        f"team {team_filter}"] if team_filter else [
                        "CODETEAM DECK", "2 UP", "2 HALTED", "▲ 123 ALERTS", "123 source errors"]
            with self.subTest(width=width, team_filter=team_filter):
                self.assertEqual([fact for fact in required if fact not in header], [], header)
                self.assertNotIn("…", header, "the clock and LANES WORKING are whole or absent")


S3_HEIGHTS = range(6, 61)
S3_WIDTHS = (80, 120)
_S3_SCREENS = {}


def s3_screens(render):
    """{(width, cursor, expanded): (the cursor's name, {height: rows})} for every sample the middle-region tests
    take, rendered once per run (660 screens) from stress_snapshot: the cursor on the first, a middle and the last
    visible session, detail off and on."""
    if not _S3_SCREENS:
        snap = stress_snapshot()
        vis = render.visible(snap)
        for cursor in (0, len(vis) // 2, len(vis) - 1):
            sid, _, session = vis[cursor]
            for expanded in (None, {sid}):
                for width in S3_WIDTHS:
                    _S3_SCREENS[width, cursor, bool(expanded)] = (session["name"], {
                        height: render.render(snap, width, cursor=cursor, expanded=expanded, height=height)
                        for height in S3_HEIGHTS})
    return _S3_SCREENS


def middle_rows(texts):
    """The screen rows between the pinned top (header, legend, blank, FLEET box) and the pinned bottom (ALERTS box
    and the key line)."""
    fleet = next((y for y, t in enumerate(texts) if t.startswith("╭─ FLEET")), None)
    if fleet is not None:
        start = next((y for y in range(fleet + 1, len(texts)) if texts[y].startswith("╰")), len(texts) - 1) + 1
    else:
        start = 0
        while start < len(texts) and ("CODETEAM DECK" in texts[start] or "■ orc" in texts[start]
                                      or not texts[start].strip()):
            start += 1
    end = len(texts) - (1 if texts and texts[-1].strip() == KEY_LINE else 0)
    end = next((y for y in range(start, end) if texts[y].startswith("╭─ ALERTS")), end)
    return texts[start:end]


# slow: the first of these tests to run renders the 660 S3 samples (~7 ms each, about 4.6 s); the rest reuse them.
class RenderMiddleTests(RenderCase):
    """The middle region with a height (plan, Rework 2, S3): every height 6..60 at 80 and 120, the cursor first, in
    the middle and last, detail off and on. Each sample lists the heights that break the rule."""

    def screens(self):
        return s3_screens(self.r).items()

    def test_never_more_rows_than_the_height(self):
        for (width, cursor, expanded), (_, screens) in self.screens():
            with self.subTest(width=width, cursor=cursor, expanded=expanded):
                self.assertEqual([h for h, rows in screens.items() if len(rows) > h], [])

    def test_the_cursor_row_shows_once_whenever_the_middle_has_a_row(self):
        for (width, cursor, expanded), (name, screens) in self.screens():
            bad = []
            for height, rows in screens.items():
                texts = [row_text(row) for row in rows]
                marked = [t for t in texts if "▸" in t]
                if middle_rows(texts) and not (len(marked) == 1 and name[:11] in marked[0]):
                    bad.append(height)
            with self.subTest(width=width, cursor=cursor, expanded=expanded):
                self.assertEqual(bad, [], f"heights without the one `▸` row of {name}")

    def test_the_focus_box_is_whole_or_absent(self):
        for (width, cursor, expanded), (_, screens) in self.screens():
            with self.subTest(width=width, cursor=cursor, expanded=expanded):
                self.assertEqual([h for h, rows in screens.items() if (coral_box(rows) or (0, True))[1] is False], [],
                                 "heights where the focus box is cut open")


class RenderDrawTests(RenderCase):
    """palette() and _placements(): what draw puts on the screen, without curses."""

    WORDS_256 = {"coral": 173, "purple": 183, "teal": 80, "blue": 111, "green": 114, "sky": 117, "amber": 221,
                 "salmon": 210, "dim": 243, "edge": 241, "faint": 238}

    def test_palette_256_gives_the_xterm_numbers(self):
        got = self.r.palette(256)
        self.assertEqual({word: got.get(word) for word in self.WORDS_256}, self.WORDS_256)

    def test_palette_under_256_gives_the_16_colour_fallback(self):
        import curses
        fallback = {"coral": curses.COLOR_RED, "purple": curses.COLOR_MAGENTA, "teal": curses.COLOR_CYAN,
                    "blue": curses.COLOR_BLUE, "green": curses.COLOR_GREEN, "sky": curses.COLOR_CYAN,
                    "amber": curses.COLOR_YELLOW, "salmon": curses.COLOR_RED}
        for colours in (8, 16):
            got = self.r.palette(colours)
            self.assertEqual({word: got.get(word) for word in fallback}, fallback, colours)
            for grey in ("dim", "edge", "faint"):
                self.assertNotIn(got.get(grey), (243, 241, 238), (colours, grey))

    def covered(self, placements, y):
        return {x + n for py, x, text, _ in placements if py == y for n in range(len(text))}

    def test_placements_keep_the_last_column_on_every_row_but_the_last_screen_row(self):
        rows = [[("a" * 6, "green"), ("b" * 4, None)] for _ in range(5)]
        got = self.r._placements(rows, 3, 10)
        self.assertEqual({y for y, _, _, _ in got}, {0, 1, 2})
        self.assertEqual(self.covered(got, 0), set(range(10)))
        self.assertEqual(self.covered(got, 1), set(range(10)))
        self.assertEqual(self.covered(got, 2), set(range(9)))
        self.assertIn((0, 0, "a" * 6, "green"), got)

    def test_placements_clip_text_to_the_width(self):
        got = self.r._placements([[("x" * 15, None)], [("y", None)]], 2, 10)
        self.assertEqual(self.covered(got, 0), set(range(10)))
        self.assertFalse([p for p in got if p[1] + len(p[2]) > 10], got)

    def test_placements_never_place_more_rows_than_the_height(self):
        rows = self.rows(tall_snapshot())
        got = self.r._placements(rows, 40, 120)
        self.assertEqual(max(y for y, _, _, _ in got), 39)


class NoLoadRunner(dict):
    """A runner whose load fields must never be read."""

    def __getitem__(self, key):
        if key in ("load", "load_max", "load_hold"):
            raise AssertionError(f"read {key}")
        return super().__getitem__(key)

    def get(self, key, default=None):
        if key in ("load", "load_max", "load_hold"):
            raise AssertionError(f"read {key}")
        return super().get(key, default)


class BuildsPanelTests(RenderCase):
    """render.py's BUILDS box. _builds gives the body rows (no border, no width); the title and its right side come
    from render()."""

    WARM = {"state": "held", "worktree": "/t/alpha/wt2", "elapsed_s": 100}
    LARGEST = {"path": "/t/alpha/wt", "part": "cargo-target", "size_gb": 12.0}

    def setUp(self):
        super().setUp()
        self.queue = render_queue()

    def panel(self, queue, warms=(), largest=()):
        return self.r._builds({"queue": queue, "warms": list(warms), "largest": list(largest), "procs": {}})

    def live(self, **fields):
        """The empty queue with a live runner: the box shows, with no job, wait or warm under it."""
        return {**render_empty_queue(), "runner": render_runner(**fields)}

    def row(self, rows, pattern):
        """The one row whose text matches pattern."""
        found = [row for row in rows if re.search(pattern, row_text(row))]
        self.assertEqual(len(found), 1, f"rows matching {pattern!r}: {[row_text(r) for r in rows]}")
        return found[0]

    def text(self, rows):
        return "\n".join(row_text(row) for row in rows)

    def title(self, builds, width=80):
        snap = copy.deepcopy(self.snap)
        snap["builds"] = builds
        rows = self.rows(snap, width)
        return self.box(rows, "BUILDS · queue")

    def test_strip_is_running_then_queued_without_broken(self):
        strip = self.panel(self.queue)[0]
        self.assertEqual(row_text(strip), "█" * 6)
        colours = [colour_at(strip, n) for n in range(6)]
        self.assertEqual([has(c, "green") for c in colours], [True] * 3 + [False] * 3)
        self.assertEqual([has(c, "faint") for c in colours], [False] * 3 + [True] * 3)
        self.assertFalse(any(has(c, "salmon") for c in colours))

    def test_counts_row_omits_any_broken_count(self):
        for broken in (1, 0, 7):
            with self.subTest(broken=broken):
                queue = copy.deepcopy(self.queue)
                queue_class(queue, "pre")["broken"] = broken
                row = self.row(self.panel(queue), "running")
                self.assertEqual(row_text(row), "■ 3 running   ■ 3 queued")

    def test_a_live_runner_shows_budget_and_swap_and_no_load_reading(self):
        rows = self.panel(self.queue)
        row = row_text(self.row(rows, "budget"))
        self.assertIn("budget ▕███   ▏ 3/6", row)
        self.assertIn("swap ▕██▌  ▏ 50%", row)
        self.assertNotIn("load", self.text(rows).lower())

    def test_a_runner_number_that_is_none_prints_a_question_mark_and_never_nan(self):
        for changes, shown in (({"used": None}, "?/6"), ({"budget": None}, "3/?"), ({"swap": None}, "swap ?")):
            row = row_text(self.row(self.panel(self.live(**changes)), "budget"))
            self.assertIn(shown, row, changes)
            self.assertNotIn("nan", row)
        row = row_text(self.row(self.panel(self.live(used=None, budget=None, swap=None, swap_max=None)), "budget"))
        self.assertIn("?/?", row)
        self.assertIn("swap ?", row)
        self.assertNotIn("nan", row)

    def test_the_swap_bar_is_salmon_only_while_the_swap_hold_is_set_and_swap_is_known(self):
        def salmon_after_swap(**fields):
            row = self.row(self.panel(self.live(**fields)), "budget")
            at = row_text(row).index("swap")
            return any(has(colour_at(row, n), "salmon") for n in range(at, len(row_text(row))))
        self.assertTrue(salmon_after_swap(swap_hold=True))
        self.assertFalse(salmon_after_swap(swap_hold=False))
        self.assertFalse(salmon_after_swap(swap_hold=True, swap=None))

    def test_a_runner_without_load_fields_renders_and_they_are_never_read(self):
        bare = {k: v for k, v in render_runner().items() if k not in ("load", "load_max", "load_hold")}
        nones = render_runner(load=None, load_max=None, load_hold=None)
        for runner in (bare, nones, NoLoadRunner(bare), NoLoadRunner(render_runner())):
            with self.subTest(runner=dict(runner)):
                queue = {**self.queue, "runner": runner}
                self.assertIn("budget", self.text(self.panel(queue)))
                snap = copy.deepcopy(self.snap)
                snap["builds"]["queue"] = queue
                self.assertIn("BUILDS", "\n".join(row_text(r) for r in self.r.render(snap, 120)))

    def test_no_load_anywhere_in_the_builds_box(self):
        for width in (80, 120):
            text = "\n".join(t for _, t, _ in self.title(render_snapshot()["builds"], width))
            self.assertNotIn("load", text.lower(), width)

    def test_a_stale_runner_says_so_in_amber_with_its_age_and_no_numbers(self):
        queue = {**render_empty_queue(), "runner": render_runner(state="stale", beat_age_s=125)}
        rows = self.panel(queue, warms=[self.WARM])
        row = self.row(rows, "no live runner")
        self.assertIn("no live runner (last beat 2m ago)", row_text(row))
        self.assertWord(colour_of(row, "no live runner"), "amber", "stale")
        self.assertNotIn("budget", self.text(rows))

    def test_a_runner_that_is_none_or_unreadable_says_no_live_runner_in_amber(self):
        for state in ("none", "?"):
            row = self.row(self.panel({**render_empty_queue(), "runner": render_runner(state=state)},
                                      warms=[self.WARM]), "no live runner")
            self.assertNotIn("last beat", row_text(row), state)
            self.assertWord(colour_of(row, "no live runner"), "amber", state)

    def test_a_runner_that_is_not_live_alone_shows_no_box(self):
        for state in ("stale", "none", "?"):
            self.assertEqual(self.panel({**render_empty_queue(), "runner": render_runner(state=state)}), [], state)

    def test_a_live_runner_alone_shows_the_box(self):
        self.assertIn("budget", self.text(self.panel(self.live())))

    def test_title_counts_jobs_without_unreadable(self):
        for unknown in (1, 0, 7):
            for state in ("ok", "?"):
                with self.subTest(unknown=unknown, state=state):
                    builds = render_snapshot()["builds"]
                    builds["queue"].update(unknown=unknown, state=state)
                    row, text, x0 = self.title(builds)[0]
                    self.assertInOrder(text, "BUILDS · queue", "6 jobs")
                    self.assertWord(colour_at(row, x0), "green", "border")
                    self.assertEqual("queue ?" in text, state == "?")
                    self.assertNotIn("unreadable", text)

    def test_broken_jobs_alone_show_no_box(self):
        queue = render_empty_queue()
        queue_class(queue, "pre")["broken"] = 1
        self.assertEqual(self.panel(queue), [])

    def test_neither_broken_nor_unreadable_appears_in_the_box_at_80_or_120(self):
        for width in (80, 120):
            for word in ("broken", "unreadable"):
                with self.subTest(width=width, word=word):
                    text = "\n".join(t for _, t, _ in self.title(render_snapshot()["builds"], width))
                    self.assertNotIn(word, text.lower())

    def test_an_unreadable_file_alone_shows_no_box(self):
        self.assertEqual(self.panel({**render_empty_queue(), "unknown": 1}), [])

    def test_queue_question_mark_shows_on_the_title_only_when_the_box_shows_for_another_reason(self):
        empty = {**render_empty_queue(), "state": "?"}
        row, text, x0 = self.title({"queue": empty, "warms": [self.WARM], "largest": [], "procs": {}})[0]
        self.assertIn("queue ?", text)
        self.assertWord(colour_of(row, "queue ?", x0), "amber", "queue ?")
        snap = copy.deepcopy(self.snap)
        snap["builds"] = {"queue": empty, "warms": [], "largest": [], "procs": {}}
        self.assertNotIn("BUILDS", self.screen(snap, 80))

    def test_class_chips_show_running_over_ceiling_and_zero_is_infinity(self):
        row = self.row(self.panel(self.queue), "full 1/1")
        self.assertInOrder(row_text(row), "full 1/1", "post 0/2", "pre 0/2", "dev 2/∞")
        self.assertWord(colour_of(row, "full"), "teal", "class")
        self.assertWord(colour_of(row, "full"), "bold", "class")
        queued = render_job("p-q1", "post", "queued", position=1, waiting_s=30)
        queue = {**render_empty_queue(), "classes": [render_class("post", 0, queued=[queued])]}
        self.assertIn("post 0/∞", self.text(self.panel(queue)))

    def test_running_jobs_longest_first_with_session_timer_kind_cost_and_worktree_last(self):
        rows = self.panel(self.queue)
        full, dev2, slot = (self.row(rows, p) for p in (r"f-run\s*$", r"d-run2\s*$", r"d-run\s*$"))
        self.assertLess(rows.index(full), rows.index(dev2))
        self.assertLess(rows.index(dev2), rows.index(slot))
        self.assertInOrder(row_text(full), "●", "alpha · Coord-a", "10:00", "run", "cost 4.0", "f-run")
        self.assertInOrder(row_text(slot), "●", "alpha · Coord-b", "pid gone", "1:00", "slot", "cost 1.0", "d-run")
        self.assertWord(colour_of(full, "cost 4.0"), "dim", "cost")

    def test_a_cost_of_zero_prints_zero_and_an_unknown_cost_a_question_mark(self):
        for cost, shown in ((0.0, "cost 0.0"), (None, "cost ?")):
            running = render_job("f-run", "full", "running", session="Coord-a", started=NOW - 600, pid=4242,
                                 cost=cost, running_s=600, pid_alive=True)
            queue = {**render_empty_queue(), "classes": [render_class("full", 1, [running])]}
            self.assertIn(shown, row_text(self.row(self.panel(queue), r"f-run\s*$")), cost)

    def test_a_job_with_no_kind_shows_a_question_mark(self):
        running = render_job("f-run", "full", "running", kind=None, session="Coord-a", running_s=60)
        queue = {**render_empty_queue(), "classes": [render_class("full", 1, [running])]}
        self.assertInOrder(row_text(self.row(self.panel(queue), r"f-run\s*$")), "alpha · Coord-a", "1:00", "?")

    def test_pid_gone_is_salmon_only_when_pid_alive_is_false(self):
        rows = self.panel(self.queue)
        self.assertWord(colour_of(self.row(rows, r"d-run\s*$"), "pid gone"), "salmon", "pid gone")
        self.assertNotIn("pid gone", row_text(self.row(rows, r"f-run\s*$")))
        unknown = copy.deepcopy(self.queue)
        queue_class(unknown, "dev")["running"][0]["pid_alive"] = None
        self.assertNotIn("pid gone", row_text(self.row(self.panel(unknown), r"d-run\s*$")))

    def test_queued_jobs_in_the_order_given_with_position_wait_start_and_worktree(self):
        rows = self.panel(self.queue)
        first, second, third = (self.row(rows, p) for p in (r"d-q1\s*$", r"d-q2\s*$", r"d-q3\s*$"))
        self.assertLess(rows.index(first), rows.index(second))
        self.assertLess(rows.index(second), rows.index(third))
        self.assertInOrder(row_text(first), "#1 alpha · Coord-b", "held warm", "wait 3m",
                           f"start {hhmm(NOW + 1800)}", "d-q1")
        self.assertInOrder(row_text(second), "#2 alpha · Orc-Alpha", "wait 1m", "start ?", "d-q2")
        self.assertInOrder(row_text(third), "#? alpha · Coord-c", "wait 50s", "start ?", "d-q3")
        self.assertWord(colour_of(second, "wait "), "dim", "queued row")

    def test_a_queued_hold_shows_in_amber_and_nothing_when_unset(self):
        rows = self.panel(self.queue)
        self.assertWord(colour_of(self.row(rows, r"d-q1\s*$"), "held warm"), "amber", "hold")
        self.assertNotIn("held", row_text(self.row(rows, r"d-q2\s*$")))

    def test_at_120_the_queued_hold_and_pid_gone_show_uncut_in_the_box(self):
        box = self.box(self.rows(), "BUILDS · queue")
        self.assertInOrder(self.line(box, "#1 alpha · Coord-b")[1], "#1 alpha · Coord-b", "held warm", "wait 3m")
        self.assertIn("pid gone", self.line(box, "● alpha · Coord-b")[1])

    def test_waits_per_class_with_waits_name_the_window(self):
        rows = self.panel(self.queue)
        row = self.row(rows, r"waits \d+h ·")
        self.assertIn("waits 24h · full · 3 · med 2m · max 10m", row_text(row))
        self.assertWord(colour_of(row, "waits"), "dim", "waits")
        queue = {**render_empty_queue(),
                 "classes": [render_class("full", 1, n=3, median_s=120.0, max_s=600.0, window_h=6),
                             render_class("pre", 2, broken=1, window_h=6)]}
        text = self.text(self.panel(queue))
        self.assertIn("waits 6h · full · 3 · med 2m · max 10m", text)
        self.assertNotIn("· pre ·", text)

    def test_no_broken_jobs_per_class_row(self):
        self.assertNotIn("× pre broken 1", self.text(self.panel(self.queue)))

    def test_warm_rows(self):
        row = self.row(self.panel({}, warms=[self.WARM]), "warm held")
        self.assertInOrder(row_text(row), "warm", "held", "1m", "wt2")
        self.assertWord(colour_of(row, "warm"), "dim", "warm")

    def test_the_box_is_empty_when_nothing_is_active_whatever_the_queue_state(self):
        for state in ("ok", "?"):
            self.assertEqual(self.panel({**render_empty_queue(), "state": state}), [], state)

    def test_a_warm_alone_shows_the_box_and_a_largest_row_alone_does_not(self):
        self.assertTrue(self.panel(render_empty_queue(), warms=[self.WARM]))
        self.assertEqual(self.panel(render_empty_queue(), largest=[self.LARGEST]), [])
        self.assertNotIn("largest", self.text(self.panel(self.queue, largest=[self.LARGEST])))

    def test_a_queue_in_the_old_list_shape_is_read_as_empty(self):
        self.assertEqual(self.panel([{"pid": 555, "since": NOW - 30, "waiting_s": 30}]), [])

    def test_a_queue_that_is_none_renders_as_empty(self):
        self.assertEqual(self.panel(None), [])

    def test_a_job_entry_that_is_not_a_dict_is_skipped_and_the_rest_still_render(self):
        queue = copy.deepcopy(self.queue)
        queue_class(queue, "full")["running"].insert(0, "junk")
        queue_class(queue, "dev")["queued"].insert(0, 7)
        rows = self.panel(queue)
        self.assertInOrder(row_text(self.row(rows, r"f-run\s*$")), "alpha · Coord-a", "10:00")
        self.row(rows, r"d-q1\s*$")
        self.row(rows, r"d-q2\s*$")

    def test_a_runner_that_is_not_a_dict_never_raises_and_the_rest_renders(self):
        for runner in ("junk", None, [1, 2], 7):
            rows = self.panel({**self.queue, "runner": runner})
            self.assertIn("#1 alpha · Coord-b", row_text(self.row(rows, r"d-q1\s*$")), repr(runner))
            self.assertIn("no live runner", self.text(rows), repr(runner))

    def test_a_class_that_is_not_a_dict_is_skipped_and_the_rest_still_render(self):
        queue = {**self.queue, "classes": ["junk", None, *self.queue["classes"]]}
        self.row(self.panel(queue), r"f-run\s*$")

    def test_no_slot_number_or_slots_word_appears_in_the_builds_box(self):
        text = self.text(self.r._builds(render_snapshot()["builds"]))
        for name in ("slot0", "slot1", "slot2", "slot3", "slots"):
            self.assertNotIn(name, text)

    def test_env_and_command_never_reach_the_screen_at_120_or_80_columns(self):
        snap = render_snapshot()
        jobs = [job for c in snap["builds"]["queue"]["classes"] for job in c["running"] + c["queued"]]
        for job in jobs:
            job.update(env={"ZONE_TOKEN": "env-marker-4417"}, command="make zone-test-one DIR=cmd-marker-9021")
        for width in (120, 80):
            text = self.screen(snap, width)
            self.assertNotIn("env-marker-4417", text, width)
            self.assertNotIn("cmd-marker-9021", text, width)


class FakeDeckHerdr(Herdr):
    """A herdr whose run() is faked: each call's args are recorded, and the answers come from in-memory workspaces
    and panes. With `fail` set, every call raises it."""

    def __init__(self, workspaces, panes, fail=None):
        super().__init__("codeteam")
        self.workspaces, self.panes, self.fail = workspaces, panes, fail
        self.calls = []

    def run(self, *args, timeout=None, raw=False):
        self.calls.append(args)
        if self.fail:
            raise self.fail
        verb = args[:2]
        if verb == ("workspace", "list"):
            return {"workspaces": self.workspaces}
        if verb == ("workspace", "create"):
            self.workspaces.append({"workspace_id": "w2", "label": "deck"})
            self.panes.append({"pane_id": "p2", "workspace_id": "w2", "label": None})
            return {"workspace": {"workspace_id": "w2"}, "tab": {"tab_id": "t2"}, "root_pane": {"pane_id": "p2"}}
        if verb == ("pane", "list"):
            ws = args[3] if len(args) > 3 else None
            return {"panes": [p for p in self.panes if ws in (None, p["workspace_id"])]}
        if verb == ("pane", "rename"):
            for p in self.panes:
                if p["pane_id"] == args[2]:
                    p["label"] = args[3]
            return {}
        if verb == ("pane", "run"):
            return {}
        raise AssertionError(f"the deck made an unexpected herdr call: {args}")

    def verbs(self):
        return {call[:2] for call in self.calls}


class AppTests(unittest.TestCase):
    """app.py and the hook-in in cli.main: --json, the route before a team is built, and --pane."""

    def run_main(self, *argv):
        from codeteam2.cli import main
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_json_prints_the_collected_snapshot_for_the_named_team(self):
        snap = {"version": 1, "at": NOW, "teams": []}
        with patch("codeteam2.deck.collect.collect", return_value=snap) as collect:
            code, out, _ = self.run_main("deck", "--json", "x")
        self.assertEqual(code, 0)
        collect.assert_called_once()
        self.assertEqual(tuple(collect.call_args.args[0]), ("x",))
        self.assertEqual(json.loads(out), snap)

    def test_deck_is_routed_before_any_team_is_built(self):
        snap = {"version": 1, "at": NOW, "teams": []}
        with patch("codeteam2.cli.Team") as team, patch("codeteam2.deck.collect.collect", return_value=snap):
            self.run_main("deck", "--json", "x")
        team.assert_not_called()

    def test_pane_creates_the_deck_workspace_and_runs_the_deck_in_its_pane(self):
        from codeteam2.team import CODETEAM2
        fake = FakeDeckHerdr([{"workspace_id": "w1", "label": "tessa"}],
                             [{"pane_id": "p1", "workspace_id": "w1", "label": "tessa-orc"}])
        with patch("codeteam2.deck.app.Herdr", return_value=fake):
            code, _, _ = self.run_main("deck", "--pane", "acme", "widgets")
        self.assertEqual(code, 0)
        self.assertEqual(fake.verbs(), {("workspace", "list"), ("workspace", "create"), ("pane", "list"),
                                        ("pane", "rename"), ("pane", "run")})
        self.assertIn(("pane", "rename", "p2", "deck"), fake.calls)
        self.assertIn(("pane", "run", "p2", f"{CODETEAM2} deck acme widgets"), fake.calls)

    def test_pane_reuses_a_running_deck_pane_and_runs_nothing(self):
        fake = FakeDeckHerdr([{"workspace_id": "w9", "label": "deck"}],
                             [{"pane_id": "p5", "workspace_id": "w9", "label": "deck"}])
        with patch("codeteam2.deck.app.Herdr", return_value=fake):
            code, out, _ = self.run_main("deck", "--pane")
        self.assertEqual(code, 0)
        self.assertIn("deck already running in pane p5", out)
        self.assertFalse({("pane", "run"), ("pane", "rename"), ("workspace", "create")} & fake.verbs())

    def test_a_herdr_error_prints_and_returns_1(self):
        fake = FakeDeckHerdr([], [], fail=HerdrError("exit", "boom"))
        with patch("codeteam2.deck.app.Herdr", return_value=fake):
            code, out, err = self.run_main("deck", "--pane")
        self.assertEqual(code, 1)
        self.assertIn("herdr:", out + err)
        self.assertIn("boom", out + err)

    def run_pane_with(self, fake):
        """`deck --pane` with herdr replaced by fake. An error that escapes main is reported as a failed assertion."""
        with patch("codeteam2.deck.app.Herdr", return_value=fake):
            try:
                return self.run_main("deck", "--pane")
            except Exception as e:
                self.fail(f"--pane let {type(e).__name__} escape instead of printing it: {e}")

    def test_pane_prints_a_herdr_timeout_and_returns_1(self):
        fake = FakeDeckHerdr([], [], fail=subprocess.TimeoutExpired(["herdr", "workspace", "list"], 10))
        code, out, err = self.run_pane_with(fake)
        self.assertEqual(code, 1)
        self.assertIn("herdr:", out + err)
        self.assertNotIn("Traceback", out + err)

    def test_pane_prints_a_missing_herdr_binary_and_returns_1(self):
        fake = FakeDeckHerdr([], [], fail=FileNotFoundError(2, "No such file or directory", "herdr"))
        code, out, err = self.run_pane_with(fake)
        self.assertEqual(code, 1)
        self.assertIn("herdr:", out + err)
        self.assertNotIn("Traceback", out + err)


class ReadOnlyHerdr:
    """The two herdr reads the deck makes (agent list, pane list), answered from a fixture."""

    def __init__(self, agents, panes):
        self.agents, self.panes = agents, panes

    def run(self, *args, timeout=None):
        if args[:2] == ("agent", "list"):
            return {"agents": self.agents}
        if args[:2] == ("pane", "list"):
            return {"panes": self.panes}
        raise AssertionError(f"the deck made an unexpected herdr call: {args}")


def write_manifest(path, product, worktree_root, repo):
    path.write_text(f'product = "{product}"\nrepo = {json.dumps(str(repo))}\nbase = "main"\n'
                    f'repo_name = "{product}"\nworktree_root = {json.dumps(str(worktree_root))}\n')


class IntegrationTests(unittest.TestCase):
    """collect() end to end over a fixture tree: tessa is a codeteam2 team, bramble is still on v1."""

    def setUp(self):
        from codeteam2.deck import collect
        from codeteam2.store import Store
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        teams_dir, projects, metrics = root / "teams", root / "projects", root / "metrics"
        queue = root / "run" / "queue"
        for d in (teams_dir, projects, metrics, queue):
            d.mkdir(parents=True)
        repo = root / "repo-tessa"
        write_manifest(teams_dir / "tessa.toml", "tessa", root / "team-tessa", repo)
        write_manifest(teams_dir / "bramble.toml", "bramble", root / "team-bramble", root / "repo-bramble")

        home = root / "team-tessa" / "team"
        home.mkdir(parents=True)
        (home / "team.json").write_text(json.dumps({"product": "tessa", "lanes": {"a": {"path": "."}}}))
        v2 = home / "v2"
        (v2 / "launch").mkdir(parents=True)
        (v2 / "up").touch()
        (v2 / "heartbeat").write_text(str(int(NOW - 5)))
        (v2 / "state.json").write_text(json.dumps({
            "orc": {"status": "working", "state_since": NOW - 600, "sid": "sid-orc"},
            "a": {"status": "blocked", "state_since": NOW - 300, "sid": "sid-a"}}))
        store = Store(v2 / "messages.db")
        mid = store.add("general", "Orc-Tessa", "REQUEST", "Coord-a", "a", "check the dialog")
        store.mark(mid, "held", "agent_blocked")
        store.db.close()
        turns = projects / "-tessa"
        turns.mkdir()
        write_jsonl(turns / "sid-orc.jsonl", [
            {"type": "user", "timestamp": iso(NOW - 700), "message": {"content": "[codeteam] hi"}},
            {"type": "assistant", "timestamp": iso(NOW - 690), "message": {"content": [{"type": "text", "text": "ok"}]}},
            {"type": "system", "subtype": "turn_duration", "timestamp": iso(NOW - 689)}])
        write_jsonl(metrics / "repo-tessa.jsonl", [{
            "ts": iso(NOW - 60), "session_id": "sid-orc", "cwd": str(repo),
            "raw": {"session_id": "sid-orc", "context_window": {"used_percentage": 42.0,
                                                               "context_window_size": 1000000},
                    "cost": {"total_cost_usd": 3.2},
                    "prompt_cache": {"warm": True, "expires_at": NOW + 1200, "hit_ratio": 0.9},
                    "model": {"id": "claude-opus"}, "effort": {"level": "high"}}}])

        self.bramble_home = root / "team-bramble" / "team"
        self.bramble_home.mkdir(parents=True)
        (self.bramble_home / "team.json").write_text(json.dumps({"product": "bramble", "lanes": {}}))

        herdr = ReadOnlyHerdr(
            agents=[{"pane_id": "p-orc", "workspace_id": "w1", "name": "tessa-orc", "agent_status": "working"},
                    {"pane_id": "p-a", "workspace_id": "w1", "name": "tessa-a", "agent_status": "blocked"}],
            panes=[{"pane_id": "p-orc", "workspace_id": "w1", "label": "tessa-orc"},
                   {"pane_id": "p-a", "workspace_id": "w1", "label": "tessa-a"}])
        self.snap = collect.collect(teams_dir=teams_dir, now=NOW, herdr=herdr, ps_text="", queue_dir=queue,
                                    metrics_dir=metrics,
                                    projects_dir=projects)

    def _team(self, name):
        return next(t for t in self.snap["teams"] if t["name"] == name)

    def _session(self, team, name):
        return next(s for s in team["sessions"] if s["name"] == name)

    def test_snapshot_is_json_and_lists_the_codeteam2_team_with_its_sessions(self):
        json.dumps(self.snap)
        tessa = self._team("tessa")
        self.assertEqual(tessa["state"], "up")
        self.assertEqual(sorted(s["name"] for s in tessa["sessions"]), ["Coord-a", "Orc-Tessa"])

    def test_session_rows_carry_their_flags_and_the_alerts_carry_their_kinds(self):
        tessa = self._team("tessa")
        orc = self._session(tessa, "Orc-Tessa")
        lane = self._session(tessa, "Coord-a")
        self.assertEqual(orc["transcript_state"], "ended")
        self.assertTrue(orc["flags"]["between_turns"])
        self.assertEqual(orc["context"]["used_pct"], 42.0)
        self.assertTrue(lane["flags"]["blocked"])
        self.assertEqual(lane["flags"]["blocked_for_s"], 300)
        self.assertTrue(lane["flags"]["held"])
        kinds = {a["kind"] for a in self.snap["alerts"]}
        self.assertTrue({"blocked", "held"} <= kinds, kinds)
        self.assertNotIn("heartbeat", kinds)

    def test_a_team_whose_v2_folder_does_not_exist_is_v1_and_gets_none_created(self):
        bramble = self._team("bramble")
        self.assertEqual(bramble["state"], "v1")
        self.assertEqual(bramble["sessions"], [])
        self.assertFalse((self.bramble_home / "v2").exists())


USER_TURN = {"type": "user", "message": {"content": "work"}}
BOUNDARY = {"type": "system", "subtype": "compact_boundary"}


def append_text(path, text):
    with open(path, "a") as f:
        f.write(text)


def metrics_row(sid, ts, cost, cwd, pad=0):
    """A status-line record of session sid: its time, its cost so far, and its folder (raw.cwd)."""
    raw = {"session_id": sid, "cwd": str(cwd), "cost": {"total_cost_usd": cost}}
    if pad:
        raw["pad"] = "x" * pad
    return {"ts": iso(ts), "session_id": sid, "cwd": str(cwd), "raw": raw}


def du_output(root, sizes_gb):
    """`du -k -d 6` lines for {path under root, '' for the root itself: size in GB}."""
    lines = []
    for rel, gb in sizes_gb.items():
        path = f"{root}/{rel}" if rel else str(root)
        lines.append(f"{int(gb * 2 ** 20)}\t{path}")
    return "\n".join(lines) + "\n"


def disk_tree(root):
    """A team folder: wt-a holds a .git file, wt-a2 (a name that starts like wt-a) and wt-b to wt-f hold a .git
    folder, a worktree is nested inside wt-a, and a plain folder holds a .build. Returns the sizes (GB) a du of it
    would print."""
    root.mkdir()
    (root / "wt-a").mkdir()
    (root / "wt-a" / ".git").write_text("gitdir: /main/.git/worktrees/wt-a\n")
    (root / "wt-a" / "nested" / ".git").mkdir(parents=True)
    for name in ("wt-a2", "wt-b", "wt-c", "wt-d", "wt-e", "wt-f"):
        (root / name / ".git").mkdir(parents=True)
    (root / "plain" / ".build").mkdir(parents=True)
    return {"": 40.0, "wt-a": 6.0, "wt-a/cargo-target": 4.0, "wt-a/src": 1.0, "wt-a/nested": 3.5,
            "wt-a2": 5.5, "wt-b": 5.0, "wt-b/cargo-target": 0.75, "wt-b/target": 2.0, "wt-b/.build": 1.0,
            "wt-b/node_modules": 1.0, "wt-b/.codegraph": 0.5, "wt-b/scratchpad": 0.25,
            "wt-c": 4.0, "wt-d": 3.0, "wt-e": 2.0, "wt-f": 1.0, "plain": 9.0, "plain/.build": 9.0}


def silent_lane_fixture(root, wt):
    """Team tessa with one working lane (session sid-a). Its one running subagent works in wt and last wrote 13
    minutes before NOW. Returns the folders collect() reads."""
    folders = {name: root / name for name in ("teams", "projects", "metrics")}
    queue = root / "run" / "queue"
    for folder in (*folders.values(), queue):
        folder.mkdir(parents=True)
    write_manifest(folders["teams"] / "tessa.toml", "tessa", root / "team-tessa", root / "repo-tessa")
    home = root / "team-tessa" / "team"
    (home / "v2" / "launch").mkdir(parents=True)
    (home / "team.json").write_text(json.dumps({"product": "tessa", "lanes": {"a": {"path": "."}}}))
    (home / "v2" / "state.json").write_text(json.dumps(
        {"a": {"status": "working", "state_since": NOW - 600, "sid": "sid-a"}}))
    turns = folders["projects"] / "-tessa"
    turns.mkdir()
    write_jsonl(turns / "sid-a.jsonl", [USER_TURN])
    subs = turns / "sid-a" / "subagents"
    subs.mkdir(parents=True)
    (subs / "agent-s1.meta.json").write_text(json.dumps({
        "agentType": "coder", "description": "port the parser", "spawnDepth": 1, "parentAgentId": None,
        "finished": False, "inheritedWorktreePath": str(wt)}))
    write_jsonl(subs / "agent-s1.jsonl", [USER_TURN])
    os.utime(subs / "agent-s1.jsonl", (NOW - 13 * MIN, NOW - 13 * MIN))
    return {"teams_dir": folders["teams"], "projects_dir": folders["projects"],
            "metrics_dir": folders["metrics"], "queue_dir": queue}


def silent_lane_snapshot(collect, root, wt, ps_text=""):
    herdr = ReadOnlyHerdr(agents=[{"pane_id": "p-a", "name": "tessa-a", "agent_status": "working"}],
                          panes=[{"pane_id": "p-a", "label": "tessa-a"}])
    return collect.collect(now=NOW, herdr=herdr, ps_text=ps_text,
                           **silent_lane_fixture(root, wt))


def lane_agent(snap):
    return snap["teams"][0]["sessions"][0]["agents"][0]


class DiskScanTests(unittest.TestCase):
    """parse_du over a fixture tree, DiskScanner.scan_pass with du patched, and collect()'s disk entries."""

    def setUp(self):
        from codeteam2.deck import collect
        self.c = collect
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def _team(self, v2):
        """A team's folder (the scanned root) and its home, with the home's v2 folder only when v2 is set."""
        root = self.root / "team-x"
        home = root / "team"
        home.mkdir(parents=True)
        if v2:
            (home / "v2").mkdir()
        return root, home

    def _scanner(self, root, home):
        return self.c.DiskScanner({"tessa": root}, interval_s=600, cache_dir_for=lambda name: home / "v2" / "deck")

    def _du(self, text):
        return patch("codeteam2.deck.collect.subprocess.run",
                     return_value=subprocess.CompletedProcess(["du"], 0, stdout=text, stderr=""))

    def test_a_worktree_is_a_folder_with_a_git_file_or_folder_and_the_walk_does_not_go_inside_one(self):
        root = self.root / "team"
        got = self.c.parse_du(du_output(root, disk_tree(root)), root)
        self.assertEqual([w["path"] for w in got["worktrees"]],
                         [f"{root}/wt-a", f"{root}/wt-a2", f"{root}/wt-b", f"{root}/wt-c", f"{root}/wt-d"])

    def test_only_the_five_largest_worktrees_are_kept_largest_first(self):
        root = self.root / "team"
        got = self.c.parse_du(du_output(root, disk_tree(root)), root)
        self.assertEqual([w["size_gb"] for w in got["worktrees"]], [6.0, 5.5, 5.0, 4.0, 3.0])
        self.assertEqual(got["size_gb"], 40.0)

    def test_part_sizes_are_kept_for_the_build_and_cache_folders_only(self):
        root = self.root / "team"
        got = {w["path"]: w["parts"] for w in self.c.parse_du(du_output(root, disk_tree(root)), root)["worktrees"]}
        self.assertEqual(got[f"{root}/wt-b"], {"cargo-target": 0.75, "target": 2.0, ".build": 1.0,
                                               "node_modules": 1.0, ".codegraph": 0.5, "scratchpad": 0.25})
        self.assertEqual(got[f"{root}/wt-a"], {"cargo-target": 4.0})

    def test_a_scan_pass_writes_the_team_disk_json_when_its_v2_folder_exists(self):
        root, home = self._team(v2=True)
        with self._du(du_output(root, {"": 2.0, "wt-a": 1.0})) as du:
            self._scanner(root, home).scan_pass()
        disk = json.loads((home / "v2" / "deck" / "disk.json").read_text())
        self.assertEqual(disk["size_gb"], 2.0)
        self.assertEqual(du.call_args.args[0], ["nice", "-n", "19", "du", "-k", "-d", "6", str(root)])

    def test_a_scan_pass_creates_nothing_when_the_team_has_no_v2_folder(self):
        root, home = self._team(v2=False)
        with self._du(du_output(root, {"": 2.0})):
            self._scanner(root, home).scan_pass()
        self.assertEqual(os.listdir(home), [])

    def test_a_scan_pass_skips_a_fresh_disk_json_until_a_scan_is_forced(self):
        root, home = self._team(v2=True)
        deck = home / "v2" / "deck"
        deck.mkdir()
        (deck / "disk.json").write_text(json.dumps({"at": time.time() - 30, "size_gb": 1.0, "worktrees": []}))
        scanner = self._scanner(root, home)
        with self._du(du_output(root, {"": 3.0})) as du:
            scanner.scan_pass()
            skipped = du.call_count
            scanner._force = True
            scanner.scan_pass()
        self.assertEqual(skipped, 0)
        self.assertEqual(json.loads((deck / "disk.json").read_text())["size_gb"], 3.0)
        self.assertEqual(du.call_count, 1)

    def test_collect_gives_a_v1_team_its_scanner_entry_and_the_scanner_entry_beats_disk_json(self):
        root = self.root
        teams = root / "teams"
        teams.mkdir()
        write_manifest(teams / "tessa.toml", "tessa", root / "team-tessa", root / "repo-tessa")
        write_manifest(teams / "bramble.toml", "bramble", root / "team-bramble", root / "repo-bramble")
        tessa_home = root / "team-tessa" / "team"
        (tessa_home / "v2" / "launch").mkdir(parents=True)
        (tessa_home / "v2" / "deck").mkdir()
        (tessa_home / "team.json").write_text(json.dumps({"product": "tessa", "lanes": {}}))
        (tessa_home / "v2" / "deck" / "disk.json").write_text(
            json.dumps({"at": NOW - 100, "size_gb": 1.0, "worktrees": []}))
        bramble_home = root / "team-bramble" / "team"
        bramble_home.mkdir(parents=True)
        (bramble_home / "team.json").write_text(json.dumps({"product": "bramble", "lanes": {}}))
        scanned = {"at": NOW, "teams": {"tessa": {"at": NOW, "size_gb": 9.0, "worktrees": []},
                                        "bramble": {"at": NOW, "size_gb": 4.0, "worktrees": []}}}
        folders = dict(teams_dir=teams, now=NOW, herdr=ReadOnlyHerdr([], []), ps_text="",
                       queue_dir=root / "run" / "queue",
                       metrics_dir=root / "metrics", projects_dir=root / "projects")
        with_scan = {t["name"]: t for t in self.c.collect(**folders, disk=scanned)["teams"]}
        alone = {t["name"]: t for t in self.c.collect(**folders)["teams"]}
        self.assertEqual(with_scan["bramble"]["state"], "v1")
        self.assertEqual(with_scan["bramble"]["disk"]["size_gb"], 4.0)
        self.assertEqual(with_scan["tessa"]["disk"]["size_gb"], 9.0)
        self.assertEqual(alone["tessa"]["disk"]["size_gb"], 1.0)
        self.assertIsNone(alone["bramble"]["disk"])


class IncrementalReadTests(unittest.TestCase):
    """The readers that follow a growing file, over one Cache shared by every read of a test."""

    def setUp(self):
        from codeteam2.deck import collect
        self.c = collect
        self.cache = collect.Cache()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_count_compactions_counts_only_the_boundaries_appended_since_the_last_read(self):
        path = self.root / "t.jsonl"
        write_jsonl(path, [BOUNDARY, USER_TURN, BOUNDARY])
        self.assertEqual(self.c.count_compactions(path, self.cache), (2, False))
        append_text(path, "".join(json.dumps(r) + "\n" for r in [USER_TURN, BOUNDARY, BOUNDARY]))
        self.assertEqual(self.c.count_compactions(path, self.cache)[0], 4)
        append_text(path, json.dumps(USER_TURN) + "\n")
        self.assertEqual(self.c.count_compactions(path, self.cache)[0], 4)

    def test_count_compactions_holds_back_an_unfinished_last_line_until_it_is_completed(self):
        path = self.root / "t.jsonl"
        write_jsonl(path, [BOUNDARY])
        self.assertEqual(self.c.count_compactions(path, self.cache)[0], 1)
        append_text(path, json.dumps(BOUNDARY)[:-1])
        self.assertEqual(self.c.count_compactions(path, self.cache)[0], 1)
        append_text(path, "}\n")
        self.assertEqual(self.c.count_compactions(path, self.cache)[0], 2)

    def test_count_compactions_reads_a_shrunk_file_from_the_start_again(self):
        path = self.root / "t.jsonl"
        write_jsonl(path, [BOUNDARY, USER_TURN, BOUNDARY, USER_TURN, BOUNDARY])
        self.assertEqual(self.c.count_compactions(path, self.cache)[0], 3)
        write_jsonl(path, [BOUNDARY])
        self.assertEqual(self.c.count_compactions(path, self.cache), (1, False))

    def test_seat_cost_today_counts_todays_sessions_inside_the_worktree_root_and_later_records(self):
        root = self.root / "wt-tessa"
        log = self.root / "wt-tessa.jsonl"
        write_jsonl(log, [
            metrics_row("s-in", NOW - 6 * HOUR, 1.0, root / "sub"),
            metrics_row("s-in", NOW - HOUR, 2.5, root / "sub"),
            metrics_row("s-yesterday", NOW - 17 * HOUR, 5.0, root),
            metrics_row("s-outside", NOW - 2 * HOUR, 7.0, root.parent / (root.name + "2")),
        ])
        self.assertEqual(self.c.seat_cost_today(log, NOW, self.cache, root=str(root)), 2.5)
        self.assertEqual(self.c.seat_cost_today(log, NOW, self.cache), 9.5)
        append_text(log, json.dumps(metrics_row("s-new", NOW - 30 * MIN, 0.5, root)) + "\n")
        self.assertEqual(self.c.seat_cost_today(log, NOW, self.cache, root=str(root)), 3.0)

    def test_seat_cost_today_is_a_lower_bound_when_the_log_was_first_read_from_mid_file(self):
        root = self.root / "wt-tessa"
        big = self.root / "big.jsonl"
        write_jsonl(big, [metrics_row("old", NOW - 17 * HOUR, 1.0, root, pad=150) for _ in range(400)]
                    + [metrics_row("s-in", NOW - HOUR, 4.0, root / "sub")])
        small = self.root / "small.jsonl"
        write_jsonl(small, [metrics_row("s-in", NOW - HOUR, 1.0, root / "sub")])
        self.assertEqual(self.c.seat_cost_today(big, NOW, self.cache, root=str(root)), 4.0)
        self.assertTrue(self.cache.follow[("metrics", str(big))]["partial"])
        self.assertEqual(self.c.seat_cost_today(small, NOW, self.cache, root=str(root)), 1.0)
        self.assertFalse(self.cache.follow[("metrics", str(small))]["partial"])


class NoGitTests(unittest.TestCase):
    """A manifest without repo_name, a repo whose .git/config names its origin, and a lane in a linked worktree.
    collect() names the lane's folder as v1 does, and runs no git."""

    def setUp(self):
        from codeteam2.deck import collect
        self.c = collect
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_collect_names_the_lane_folder_from_the_origin_as_v1_does_and_runs_no_git(self):
        root = self.root
        repo = root / "repo-folder"
        (repo / ".git").mkdir(parents=True)
        (repo / ".git" / "config").write_text(
            '[core]\n\trepositoryformatversion = 0\n[remote "origin"]\n'
            "\turl = git@github.com:example/acme-ee-gauges.git\n"
            "\tfetch = +refs/heads/*:refs/remotes/origin/*\n")
        team_root = root / "team-tessa"
        teams = root / "teams"
        teams.mkdir()
        (teams / "tessa.toml").write_text(f'product = "tessa"\nrepo = {json.dumps(str(repo))}\nbase = "main"\n'
                                          f'worktree_root = {json.dumps(str(team_root))}\n')
        home = team_root / "team"
        (home / "v2" / "launch").mkdir(parents=True)
        (home / "team.json").write_text(json.dumps({"product": "tessa", "lanes": {"a": {"path": "."}}}))
        gitdir = repo / ".git" / "worktrees" / "acme-ee-gauges-exchange-a"
        gitdir.mkdir(parents=True)
        (gitdir / "commondir").write_text("../..\n")
        lane = team_root / "workcrews" / "a" / "acme-ee-gauges-exchange-a"
        lane.mkdir(parents=True)
        (lane / ".git").write_text(f"gitdir: {gitdir}\n")
        herdr = ReadOnlyHerdr(agents=[{"pane_id": "p-a", "name": "tessa-a", "agent_status": "idle"}],
                              panes=[{"pane_id": "p-a", "label": "tessa-a"}])
        calls = []

        def refuse(argv, *args, **kwargs):
            calls.append(list(argv) if isinstance(argv, (list, tuple)) else str(argv).split())
            raise OSError("the deck runs no git")

        with patch("subprocess.run", side_effect=refuse), patch("subprocess.Popen", side_effect=refuse), \
                patch("subprocess.check_output", side_effect=refuse):
            snap = self.c.collect(teams_dir=teams, now=NOW, herdr=herdr, ps_text="",
                                  queue_dir=root / "run" / "queue",
                                  metrics_dir=root / "metrics", projects_dir=root / "projects")
        git_calls = [c for c in calls if c and os.path.basename(c[0]) == "git"]
        self.assertEqual(git_calls, [], calls)
        tessa = snap["teams"][0]
        self.assertNotIn("error", tessa, tessa)
        lane_row = next((s for s in tessa["sessions"] if s["name"] == "Coord-a"), None)
        self.assertIsNotNone(lane_row, tessa)
        # v1's lane_wt: <repo name>-<short target>-<lane>, the repo name from origin (repo_name_of), target exchange.
        repo_name, short_target = "acme-ee-gauges", "exchange"
        self.assertEqual(lane_row["cwd"], str(team_root / "workcrews" / "a" / f"{repo_name}-{short_target}-a"))


class BuildToolsTests(unittest.TestCase):
    """A process is a build in a worktree only when it names the worktree and runs a build tool."""

    def setUp(self):
        from codeteam2.deck import collect
        self.c = collect
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_build_procs_leaves_out_tail_and_less_that_only_name_the_worktree(self):
        ps = self.c.read_ps(
            "  PID ELAPSED ARGS\n"
            " 3001 13:00 tail -f /a/wt/log\n"
            " 3002 13:00 less /a/wt/x\n"
            " 3003 02:00 cargo build --manifest-path /a/wt/Cargo.toml\n"
            " 3004 02:00 make -C /a/wt\n")
        self.assertEqual(sorted(p["pid"] for p in self.c.build_procs(ps, "/a/wt")), [3003, 3004])

    def test_a_silent_agent_named_only_by_a_tail_or_less_process_is_stalled(self):
        wt = self.root / "wt-a"
        ps_text = f"  PID ELAPSED ARGS\n 3001 13:00 tail -f {wt}/log\n 3002 13:00 less {wt}/x\n"
        snap = silent_lane_snapshot(self.c, self.root, wt, ps_text)
        self.assertTrue(lane_agent(snap)["flags"]["stalled"])

    def test_a_silent_agent_with_a_cargo_build_in_its_worktree_is_not_stalled(self):
        # Guards the build half of the rule: a real build in the worktree is never a stall.
        wt = self.root / "wt-a"
        ps_text = f"  PID ELAPSED ARGS\n 3002 02:00 cargo build --manifest-path {wt}/Cargo.toml\n"
        snap = silent_lane_snapshot(self.c, self.root, wt, ps_text)
        self.assertFalse(lane_agent(snap)["flags"]["stalled"])


class PsFailureTests(unittest.TestCase):
    """When ps did not answer, a silent agent is not stalled (no process list says it has no build), and the
    snapshot's errors name ps."""

    def setUp(self):
        from codeteam2.deck import collect, model
        self.c, self.m = collect, model
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_a_silent_agent_is_not_stalled_when_the_process_list_is_none(self):
        agent = {"id": "s1", "type": "coder", "description": "port", "depth": 1, "parent": None, "finished": False,
                 "worktree": "/t/wt-a", "started": NOW - HOUR, "last_write": NOW - 13 * MIN, "last_state": "in-turn",
                 "tokens": None}
        sess = {"team": "tessa", "key": "a", "name": "Coord-a", "role": "lane", "cwd": "/t/wt-s",
                "herdr": {"status": "working", "since": NOW - 600}, "transcript_state": "in-turn",
                "transcript_mtime": NOW - 60, "mail": None, "draft_since": None, "api_error": None,
                "agents": [agent]}
        team = {"name": "tessa", "state": "up", "heartbeat_age_s": 5, "cap": None, "lanes_running": 0,
                "disk": None, "sessions": [sess]}
        snap = {"version": 1, "at": NOW, "teams": [team], "volume": {"free_gb": 200.0},
                "builds": {"queue": {}, "warms": [], "largest": [], "procs": None},
                "disk_at": None, "alerts": []}
        self.m.derive(snap, NOW, dict(self.m.THRESHOLDS))
        self.assertFalse(agent["flags"]["stalled"])

    def test_when_ps_fails_the_silent_agent_is_not_stalled_and_errors_name_ps(self):
        wt = self.root / "wt-a"
        with patch("codeteam2.deck.collect.subprocess.run", side_effect=FileNotFoundError(2, "no ps", "ps")):
            snap = silent_lane_snapshot(self.c, self.root, wt, ps_text=None)
        self.assertFalse(lane_agent(snap)["flags"]["stalled"])
        self.assertTrue(any(e.startswith("ps") for e in snap["errors"]), snap["errors"])


class CacheRefreshTests(unittest.TestCase):
    """Several collect() calls over one Cache, `now` moved forward (NOW, NOW+2, NOW+5, NOW+6). Each source is changed
    on disk and the next refresh within its cadence must show it: state.json and ps every refresh, messages and the
    session sources every 5 s. Lane a is working in herdr; its subagent s1 has been silent for 13 minutes in wt."""

    def setUp(self):
        from codeteam2.deck import collect
        from codeteam2.store import Store
        self.c = collect
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.teams, self.projects = root / "teams", root / "projects"
        self.metrics, self.queue = root / "metrics", root / "run" / "queue"
        for d in (self.teams, self.projects, self.metrics, self.queue):
            d.mkdir(parents=True)
        self.wt = root / "wt-a"
        write_manifest(self.teams / "tessa.toml", "tessa", root / "team-tessa", root / "repo-tessa")
        self.home = root / "team-tessa" / "team"
        (self.home / "v2" / "launch").mkdir(parents=True)
        self.team_json = self.home / "team.json"
        self.state = self.home / "v2" / "state.json"
        self.write_lanes(["a"], at=NOW - 600)
        self.state.write_text(json.dumps({"a": {"status": "working", "state_since": NOW - 600, "sid": "sid-a"}}))
        self.touch(self.state, NOW - 600)
        self.store = Store(self.home / "v2" / "messages.db")
        self.addCleanup(self.store.db.close)
        turns = self.projects / "-tessa"
        turns.mkdir()
        self.transcript = turns / "sid-a.jsonl"
        write_jsonl(self.transcript, [USER_TURN])
        self.subs = turns / "sid-a" / "subagents"
        self.subs.mkdir(parents=True)
        self.write_subagent("s1", finished=False, last_write=NOW - 13 * MIN)
        self.touch(self.subs, NOW - 13 * MIN)
        self.cache = collect.Cache()

    def touch(self, path, at):
        """A distinct mtime, so a test never depends on the clock's resolution."""
        os.utime(path, (at, at))

    def write_lanes(self, keys, at):
        self.team_json.write_text(json.dumps({"product": "tessa", "lanes": {k: {"path": "."} for k in keys}}))
        self.touch(self.team_json, at)

    def write_subagent(self, agent_id, finished, last_write):
        meta = self.subs / f"agent-{agent_id}.meta.json"
        meta.write_text(json.dumps({"agentType": "coder", "description": "port the parser", "spawnDepth": 1,
                                    "parentAgentId": None, "finished": finished,
                                    "inheritedWorktreePath": str(self.wt)}))
        self.touch(meta, last_write)
        jsonl = self.subs / f"agent-{agent_id}.jsonl"
        write_jsonl(jsonl, [USER_TURN])
        self.touch(jsonl, last_write)

    def refresh(self, at, ps_text="", lanes=("a",)):
        """One collect() over the shared cache at time `at`; herdr shows each of `lanes` working."""
        herdr = ReadOnlyHerdr(
            agents=[{"pane_id": f"p-{k}", "name": f"tessa-{k}", "agent_status": "working"} for k in lanes],
            panes=[{"pane_id": f"p-{k}", "label": f"tessa-{k}"} for k in lanes])
        return self.c.collect(teams_dir=self.teams, now=at, herdr=herdr, ps_text=ps_text, queue_dir=self.queue,
                              metrics_dir=self.metrics,
                              projects_dir=self.projects, cache=self.cache)

    def row(self, snap, key="a"):
        return next(s for s in snap["teams"][0]["sessions"] if s["key"] == key)

    def subagent(self, snap, agent_id="s1"):
        return next(a for a in self.row(snap)["agents"] if a["id"] == agent_id)

    def test_unchanged_transcript_cwd_reads_each_metrics_candidate_once(self):
        launch = Path(self.row(self.refresh(NOW))["cwd"])
        write_jsonl(self.transcript, [{**USER_TURN, "cwd": str(launch)}])
        self.touch(self.transcript, NOW + 1)
        write_jsonl(self.metrics / f"{launch.name}.jsonl", [metrics_row("sid-a", NOW, 1.25, launch)])
        with patch.object(self.c, "read_metrics", wraps=self.c.read_metrics) as read_metrics:
            row = self.row(self.refresh(NOW + 5))
        self.assertEqual(row["cost"]["session_usd"], 1.25)
        self.assertEqual(read_metrics.call_count, 1)

    def test_tail_window_matches_fresh_cache_with_short_underlying_reads(self):
        real_open, real_pread = builtins.open, os.pread
        reads = []
        transcript = self.transcript

        class ShortRaw(io.RawIOBase):
            def __init__(self, raw):
                self.raw = raw

            def readable(self):
                return True

            def seekable(self):
                return True

            def seek(self, offset, whence=0):
                return self.raw.seek(offset, whence)

            def tell(self):
                return self.raw.tell()

            def readinto(self, buf):
                reads.append("buffered")
                return self.raw.readinto(memoryview(buf)[:7])

            def close(self):
                self.raw.close()
                super().close()

        def short_open(file, mode="r", *args, **kwargs):
            if str(file) == str(transcript) and mode == "rb":
                return io.BufferedReader(ShortRaw(real_open(file, mode, buffering=0)))
            return real_open(file, mode, *args, **kwargs)

        def short_pread(fd, size, offset):
            reads.append("pread")
            return real_pread(fd, min(size, 7), offset)

        tool = {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/first"}}]}}
        write_jsonl(transcript, [USER_TURN, tool])
        self.touch(transcript, NOW - 1)
        for step in range(3):
            if step == 1:
                append_text(transcript, json.dumps({"type": "system", "subtype": "turn_duration"}) + "\n")
                self.touch(transcript, NOW + 1)
            elif step == 2:
                write_jsonl(transcript, [{**USER_TURN, "message": {"content": "rebuilt"}}])
                self.touch(transcript, NOW + 2)
            reads.clear()
            with patch("builtins.open", side_effect=short_open), patch.object(os, "pread", side_effect=short_pread):
                warm = self.row(self.refresh(NOW + 5 * step))
            self.assertTrue(reads, "the transcript window did not use a capped read")
            cache, self.cache = self.cache, self.c.Cache()
            try:
                fresh = self.row(self.refresh(NOW + 5 * step))
            finally:
                self.cache = cache
            with self.subTest(step=step):
                self.assertEqual(warm, fresh)

    def test_appended_turn_is_collected_without_whole_tail_rereads(self):
        agent_path = self.subs / "agent-s1.jsonl"
        ended = {"type": "system", "subtype": "turn_duration"}
        write_jsonl(self.transcript, [USER_TURN, ended])
        write_jsonl(agent_path, [{"type": "assistant", "message": {"content": [], "usage": {"input_tokens": 1}}}])
        self.touch(self.transcript, NOW - 1)
        self.touch(agent_path, NOW - 1)
        before = self.row(self.refresh(NOW))
        self.assertEqual(before["transcript_state"], "ended")
        self.assertEqual(before["agents"][0]["last_state"], "ended")
        turn = {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/new"}}],
            "usage": {"input_tokens": 7, "output_tokens": 3}}}
        for path in (self.transcript, agent_path):
            append_text(path, json.dumps(turn) + "\n")
            self.touch(path, NOW + 1)
        with patch.object(self.c, "tail_records", side_effect=AssertionError("whole tail reread")), \
             patch("codeteam2.scheduler._tail_lines", side_effect=AssertionError("state reread")):
            snap = self.refresh(NOW + 5)
        row = next((s for s in snap["teams"][0]["sessions"] if s["key"] == "a"), {})
        self.assertEqual(row.get("transcript_state"), "in-turn", snap["teams"][0])
        self.assertEqual(row["recent"]["tools"], [{"name": "Read", "summary": "/new"}])
        self.assertEqual((row["agents"][0]["last_state"], row["agents"][0]["tokens"]), ("in-turn", 10))

    def test_incremental_tails_match_fresh_cache_and_oracles(self):
        from codeteam2.scheduler import transcript_state

        agent_path = self.subs / "agent-s1.jsonl"
        tool = {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/one"}}],
            "usage": {"input_tokens": 12, "cache_read_input_tokens": 3, "output_tokens": 2}}}
        initial = json.dumps({"type": "user", "message": {"content": "x" * (self.c.TAIL + 50)}}) + "\n"
        for path in (self.transcript, agent_path):
            path.write_text(initial + json.dumps(tool) + "\n")
            self.touch(path, NOW - 1)

        def values(snap):
            row = self.row(snap)
            return (row["transcript_state"], row["recent"]["tools"],
                    [(a["last_state"], a["tokens"]) for a in row["agents"]])

        def check(at):
            warm = values(self.refresh(at))
            cache, self.cache = self.cache, self.c.Cache()
            try:
                fresh = values(self.refresh(at))
            finally:
                self.cache = cache
            records = self.c.tail_records(agent_path)
            turns = [r for r in records if r.get("type") in ("user", "assistant")]
            last = turns[-1] if turns else {}
            content = (last.get("message") or {}).get("content") or []
            state = "?" if not turns else "ended" if last["type"] == "assistant" and not any(
                isinstance(b, dict) and b.get("type") == "tool_use" for b in content) else "in-turn"
            usage = next(((r.get("message") or {}).get("usage") for r in reversed(turns)
                          if r["type"] == "assistant" and (r.get("message") or {}).get("usage")), None)
            tokens = None if usage is None else sum(usage.get(k) or 0 for k in
                ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens"))
            oracle = (transcript_state(self.transcript, tail=self.c.TAIL)[0],
                      self.c.recent_tools(self.c.tail_records(self.transcript)), [(state, tokens)])
            self.assertEqual(warm, fresh)
            self.assertEqual(warm, oracle)

        check(NOW)
        user = {"type": "user", "cwd": str(self.wt), "message": {"content": "café"}}
        partial = json.dumps({"type": "system", "subtype": "turn_duration"})
        appends = [json.dumps(tool) + "\n", json.dumps(user, ensure_ascii=False) + "\n",
                   json.dumps({"type": "system", "subtype": "turn_duration"}) + "\n",
                   json.dumps(BOUNDARY) + "\n", json.dumps({"type": "user", "message": {"content": "a b"}},
                   ensure_ascii=False) + "\n", "not json\n", partial, "\n",
                   json.dumps({"type": "user", "message": {"content": "z" * (self.c.TAIL + 1)}}) + "\n"]
        for i, text in enumerate(appends, 1):
            for path in (self.transcript, agent_path):
                append_text(path, text)
                self.touch(path, NOW + i)
            with self.subTest(append=i):
                check(NOW + 5 * i)

        at = NOW + 5 * len(appends)
        for text in (json.dumps(USER_TURN) + "\n", json.dumps(tool) + "\n" + "x" * 100 + "\n"):
            at += 5
            for path in (self.transcript, agent_path):
                path.write_text(text)
                self.touch(path, at)
            with self.subTest(rewrite=at):
                check(at)

        # A same-size, same-mtime rename must still be noticed via inode. An in-place rewrite
        # preserving both size and the bytes before the offset is deliberately not detectable.
        for path in (self.transcript, agent_path):
            st = path.stat()
            replacement = path.with_suffix(".replacement")
            content = path.read_text().replace('"Read"', '"Edit"')
            self.assertEqual(len(content.encode()), st.st_size)
            replacement.write_text(content)
            os.utime(replacement, ns=(st.st_atime_ns, st.st_mtime_ns))
            os.replace(replacement, path)
        with self.subTest(replacement=True):
            check(at + 5)

    def test_json_snapshot_golden_and_warm_cache_after_appends(self):
        clear_queue_env(self)
        # The host's free disk would raise disk_low (under model.THRESHOLDS["disk_red_gb"]) into the alerts; a fixed
        # 100 GB keeps the snapshot independent of the machine. test_disk_low_alert_is_raised_under_50_gb_free
        # covers the alert itself.
        free_gb = patch.object(self.c, "_free_gb", return_value=100.0)
        free_gb.start()
        self.addCleanup(free_gb.stop)
        agent_path = self.subs / "agent-s1.jsonl"
        mid = self.store.add("general", "Orc-Tessa", "REQUEST", "Coord-a", "a", "check the dialog")
        self.store.db.execute("UPDATE messages SET ts=? WHERE id=?", (iso(NOW - 60), mid))
        write_jsonl(self.transcript, [{**USER_TURN, "cwd": str(self.wt)}])
        write_jsonl(self.metrics / "wt-a.jsonl", [metrics_row("sid-a", NOW - 30, 1.25, self.wt)])
        self.touch(self.transcript, NOW - 10)
        self.touch(agent_path, NOW - 20)
        snap = self.refresh(NOW, ps_text="  PID ELAPSED ARGS\n")
        # Only volatile values are normalised: temp root is random, took_s is elapsed wall time,
        # free_gb is host disk space, and started is the filesystem's creation time.
        def normalised(snapshot):
            snapshot = copy.deepcopy(snapshot)
            snapshot["took_s"] = 0
            snapshot["volume"]["free_gb"] = None
            for team in snapshot["teams"]:
                team["free_gb"] = None
                for session in team["sessions"]:
                    for agent in session["agents"]:
                        agent["started"] = None
            return json.dumps(snapshot, sort_keys=True).replace(str(self.teams.parent), "<root>")

        golden = Path(__file__).with_name("deck_snapshot_golden.json")
        # Regenerate deliberately with DECK_REGENERATE_GOLDEN=1 on the recorded test command.
        if os.environ.get("DECK_REGENERATE_GOLDEN") == "1":
            golden.write_text(json.dumps(json.loads(normalised(snap)), sort_keys=True, indent=2) + "\n")
        self.assertEqual(normalised(snap), json.dumps(json.loads(golden.read_text()), sort_keys=True))
        self.assertIsNotNone(self.row(snap)["cost"])
        self.assertEqual(len(self.row(snap)["agents"]), 1)
        self.assertEqual(self.row(snap)["mail"]["waiting"], 1)
        turn = {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/new"}}],
            "usage": {"input_tokens": 4}}}
        for path in (self.transcript, agent_path):
            append_text(path, json.dumps(turn) + "\n")
            self.touch(path, NOW + 1)
        warm = self.refresh(NOW + 5, ps_text="  PID ELAPSED ARGS\n")
        self.cache = self.c.Cache()
        fresh = self.refresh(NOW + 5, ps_text="  PID ELAPSED ARGS\n")
        warm["took_s"] = fresh["took_s"] = 0
        self.assertEqual(warm, fresh)

    def test_an_unchanged_refresh_two_seconds_later_gives_the_same_values(self):
        first = self.row(self.refresh(NOW))
        second = self.row(self.refresh(NOW + 2))
        for row in (first, second):
            self.assertEqual(row["transcript_state"], "in-turn")
            self.assertEqual([a["last_state"] for a in row["agents"]], ["in-turn"])
        self.assertEqual(self.summary(first), self.summary(second))

    def summary(self, row):
        """The fields that do not move with the clock: a cache hit must keep them."""
        return {"transcript_state": row["transcript_state"], "transcript_mtime": row["transcript_mtime"],
                "herdr": row["herdr"], "mail": row["mail"], "recent": row["recent"],
                "agents": [(a["id"], a["finished"], a["last_state"], a["last_write"], a["tokens"])
                           for a in row["agents"]]}

    def test_a_subagent_rewritten_as_finished_shows_as_finished_by_plus_5(self):
        self.assertFalse(self.subagent(self.refresh(NOW))["finished"])
        meta = self.subs / "agent-s1.meta.json"
        data = json.loads(meta.read_text())
        data["finished"] = True
        meta.write_text(json.dumps(data))
        self.touch(meta, NOW + 2)
        self.refresh(NOW + 2)
        agent = self.subagent(self.refresh(NOW + 5))
        self.assertTrue(agent["finished"])
        self.assertFalse(agent["flags"]["stalled"])

    def test_a_subagent_added_to_the_folder_with_its_jsonl_shows_by_plus_5(self):
        self.assertEqual([a["id"] for a in self.row(self.refresh(NOW))["agents"]], ["s1"])
        self.write_subagent("s2", finished=False, last_write=NOW + 2)
        self.touch(self.subs, NOW + 2)
        self.refresh(NOW + 2)
        self.assertEqual([a["id"] for a in self.row(self.refresh(NOW + 5))["agents"]], ["s1", "s2"])

    def test_a_state_json_change_shows_on_the_next_refresh(self):
        before = self.row(self.refresh(NOW))
        self.assertEqual(before["herdr"]["since"], NOW - 600)
        self.assertFalse(before["flags"]["typing"])
        self.state.write_text(json.dumps(
            {"a": {"status": "working", "state_since": NOW + 1, "sid": "sid-a", "draft_since": NOW + 1}}))
        self.touch(self.state, NOW + 2)
        after = self.row(self.refresh(NOW + 2))
        self.assertEqual(after["herdr"]["since"], NOW + 1)
        self.assertEqual(after["draft_since"], NOW + 1)
        self.assertTrue(after["flags"]["typing"])

    def test_a_message_marked_held_shows_in_the_session_mail_by_the_next_5_second_refresh(self):
        mid = self.store.add("general", "Orc-Tessa", "REQUEST", "Coord-a", "a", "check the dialog")
        self.store.db.execute("UPDATE messages SET ts=? WHERE id=?", (iso(NOW - 10 * MIN), mid))
        self.assertEqual(self.row(self.refresh(NOW))["mail"]["held"], 0)
        self.assertTrue(self.store.mark(mid, "held", "agent_blocked"))
        self.refresh(NOW + 2)
        row = self.row(self.refresh(NOW + 5))
        self.assertEqual(row["mail"]["held"], 1)
        self.assertTrue(row["flags"]["held"])

    def test_a_build_in_the_agent_worktree_clears_stalled_and_a_different_ps_text_brings_it_back(self):
        self.assertTrue(self.subagent(self.refresh(NOW))["flags"]["stalled"])
        build = f"  PID ELAPSED ARGS\n 3002 02:00 cargo build --manifest-path {self.wt}/Cargo.toml\n"
        self.assertFalse(self.subagent(self.refresh(NOW + 2, ps_text=build))["flags"]["stalled"])
        self.assertTrue(self.subagent(self.refresh(NOW + 6, ps_text="  PID ELAPSED ARGS\n"))["flags"]["stalled"])

    def test_a_lane_added_to_team_json_gets_a_row_on_the_next_refresh(self):
        before = self.refresh(NOW, lanes=("a", "b"))
        self.assertNotIn("b", [s["key"] for s in before["teams"][0]["sessions"]])
        self.write_lanes(["a", "b"], at=NOW + 2)
        row = self.row(self.refresh(NOW + 2, lanes=("a", "b")), key="b")
        self.assertEqual(row["herdr"]["status"], "working")
        self.assertEqual(row["role"], "lane")

    def test_an_end_of_turn_record_appended_while_herdr_says_working_shows_between_turns_by_plus_5(self):
        self.assertFalse(self.row(self.refresh(NOW))["flags"]["between_turns"])
        append_text(self.transcript, json.dumps({"type": "system", "subtype": "turn_duration"}) + "\n")
        self.touch(self.transcript, NOW + 2)
        self.refresh(NOW + 2)
        row = self.row(self.refresh(NOW + 5))
        self.assertEqual(row["transcript_state"], "ended")
        self.assertTrue(row["flags"]["between_turns"])

    def test_a_refresh_an_hour_on_prunes_unused_entries_and_keeps_the_live_session_and_its_output(self):
        first = self.row(self.refresh(NOW))
        ghost_run, ghost_meta = ("session", "tessa", "ghost", "sid-ghost"), str(self.subs / "agent-ghost.meta.json")
        self.cache.runs[ghost_run] = (NOW, None)
        self.cache.metas[ghost_meta] = ((1, 1), {"finished": True})
        second = self.row(self.refresh(NOW + self.c.RECENT_END_S + 60))
        # dict.keys(), not `in`: a _Kept membership test would stamp the key as used again.
        self.assertNotIn(ghost_run, dict.keys(self.cache.runs))
        self.assertNotIn(ghost_meta, dict.keys(self.cache.metas))
        self.assertIn(("session", "tessa", "a", "sid-a"), dict.keys(self.cache.runs))
        self.assertIn(str(self.subs / "agent-s1.meta.json"), dict.keys(self.cache.metas))
        self.assertEqual(second["transcript_state"], "in-turn")
        self.assertEqual(self.summary(second), self.summary(first))


def box_span(texts, title):
    """(top row, bottom row, left column, right column) of the first box titled `title`."""
    y, x0, x1 = find_box(texts, title)
    for bottom in range(y + 1, len(texts)):
        if texts[bottom][x0:x0 + 1] == "╰":
            return y, bottom, x0, x1
    raise AssertionError(f"the box {title!r} never closes:\n" + "\n".join(texts))


def has_box(texts, title):
    try:
        find_box(texts, title)
    except AssertionError:
        return False
    return True


def quiet_messages():
    """A team's messages with nothing in the log: its box is the from and to rows."""
    return {"hourly": [0] * 24, "last_hour": 0, "top_senders": [], "top_recipients": [], "broadcasts_today": 0,
            "queued": 0, "held": 0, "delivered_today": 0, "last": [], "by_target": {}, "max_id": 0}


def plain_team(name, sessions, disk=None):
    """An up team with `sessions` plain lane sessions: its box is 4 rows plus one per session."""
    return {"name": name, "manifest": f"/m/{name}.toml", "home": f"/t/{name}/team", "root": f"/t/{name}",
            "state": "up", "heartbeat_age_s": 5, "cap": 2, "running": sessions, "lanes_running": 0,
            "mail_waiting": 0, "msgs_last_hour": 0, "free_gb": 300.0, "messages": quiet_messages(), "disk": disk,
            "sessions": [render_session(name, f"k{n}", f"{name}-s{n}", "lane") for n in range(sessions)]}


def plain_snapshot(teams, largest=()):
    return {"version": 1, "at": NOW, "took_s": 0.1, "errors": [], "volume": {"free_gb": 300.0}, "teams": teams,
            "builds": {"queue": render_empty_queue(), "warms": [], "largest": list(largest), "procs": {}},
            "disk_at": NOW - 600, "alerts": []}


class RenderMasonryTests(RenderCase):
    """deck-fixes item 1: at 180 columns each team box goes at the foot of the shorter column, the left on a tie."""

    def test_at_180_each_box_goes_under_the_shorter_column_and_under_180_one_column_is_unchanged(self):
        # Box heights 10, 4, 4, 4 (4 is the shortest a team box can be): the left column takes the 10, and the
        # right column, shorter until it reaches 12, takes the other three, as the contract's 10, 3, 3, 3 does.
        snap = plain_snapshot([plain_team("tall", 6), plain_team("m2", 0), plain_team("m3", 0), plain_team("m4", 0)])
        titles = ("tall · 6 sessions", "m2 · 0 sessions", "m3 · 0 sessions", "m4 · 0 sessions")
        texts = self.texts(snap, 180)
        self.assertEqual(broken_boxes(texts), [])
        spans = [box_span(texts, title) for title in titles]
        self.assertEqual([y1 - y0 + 1 for y0, y1, _, _ in spans], [10, 4, 4, 4], "\n".join(texts))
        box_width = (180 - 54 - 1) // 2
        self.assertEqual([x0 for _, _, x0, _ in spans], [0] + [box_width + 1] * 3, "\n".join(texts))
        self.assertEqual(spans[1][0], spans[0][0], "\n".join(texts))
        for above, below in zip(spans[1:], spans[2:]):
            self.assertEqual(below[0], above[1] + 1, "no blank row between stacked boxes:\n" + "\n".join(texts))
        for i, a in enumerate(spans):
            for b in spans[i + 1:]:
                apart = a[1] < b[0] or b[1] < a[0] or a[3] < b[2] or b[3] < a[2]
                self.assertTrue(apart, f"{a} overlaps {b}:\n" + "\n".join(texts))
        texts = self.texts(snap, 150)
        spans = [box_span(texts, title) for title in titles]
        self.assertEqual([(x0, x1) for _, _, x0, x1 in spans], [(0, 150 - 54 - 1)] * 4, "\n".join(texts))
        for above, below in zip(spans, spans[1:]):
            self.assertEqual(below[0], above[1] + 1, "\n".join(texts))


class RenderBudgetUsedTests(RenderCase):
    """deck-fixes item 2: the BUILDS used budget is the nearest whole number, halves up; its gauge is a six-cell
    eighth-block bar of the unrounded value (deck-motion B2)."""

    def budget_body(self, used):
        snap = copy.deepcopy(self.snap)
        snap["builds"] = {"queue": {**render_empty_queue(), "runner": render_runner(used=used, budget=6)},
                          "warms": [], "largest": [], "procs": {}}
        return next(body for body in box_bodies(self.texts(snap), "BUILDS · queue") if "budget" in body)

    def test_the_used_budget_is_rounded_halves_up_and_a_missing_one_is_a_question_mark(self):
        # 6 cells are 48 eighths: 5.00926/6 is 40, 3.5/6 is 28, 2.5/6 is 20.
        for used, shown, bar in ((5.00926, "5/6", "█████ "), (3.5, "4/6", "███▌  "), (2.5, "3/6", "██▌   "),
                                 (None, "?/6", None)):
            with self.subTest(used=used):
                body = self.budget_body(used)
                gauge = re.search(r"budget (\?|▕.{6}▏) (\S+)   swap", body)
                self.assertIsNotNone(gauge, body)
                self.assertEqual(gauge[2], shown, body)
                self.assertEqual(gauge[1], "?" if bar is None else f"▕{bar}▏", body)


DISK_TEAMS = ("acme", "gears", "gadgets", "gizmos", "gauges", "codeteam", "sprockets", "nagatha")
DISK_PARTS = {"node_modules": 12.3, "target": 8.8, ".codegraph": 1.2, "scratchpad": 0.4}


def disk_fleet_snapshot():
    """The live shape of item 3: 8 up teams, each measured with 5 worktrees whose build parts wrap onto a second
    row, and 3 sessions per team so the team column is taller than any screen; the cursor's team is acme."""
    teams = []
    for i, name in enumerate(DISK_TEAMS):
        worktrees = [{"path": f"/t/{name}/{name[:5]}-wt{n}", "size_gb": 50.0 - n, "parts": dict(DISK_PARTS)}
                     for n in range(5)]
        teams.append(plain_team(name, 3, {"size_gb": 400.0 - 40 * i, "worktrees": worktrees}))
    return plain_snapshot(teams, [{"path": "/t/acme/acme-wt0", "part": "node_modules", "size_gb": 12.3},
                                  {"path": "/t/gizmos/gizmos-wt0", "part": "target", "size_gb": 8.8}])


def disk_room(texts):
    """The rows the screen leaves for DISK under the log box: from the row after the log's bottom border to the row
    above the key line (the screen has no alerts)."""
    return len(texts) - 1 - (box_span(texts, "log · ")[1] + 1)


def disk_names(bodies):
    """The team names of the DISK rows: the rows that start at the box's first column, other than `largest`."""
    return [body.split()[0] for body in bodies if body and not body.startswith((" ", "largest"))]


def disk_order_fixture():
    """(teams, snapshot) for _disk: beta (200G, 2 one-row worktrees) listed before alpha (300G, 6 worktrees, the
    first with every WRAP_PARTS so it wraps, the rest one row each), then gamma, not measured; 3 largest rows."""
    def worktree(path, parts):
        return {"path": path, "size_gb": 10.0, "parts": parts}

    teams = [{"name": "beta", "disk": {"size_gb": 200.0, "worktrees": [worktree("/t/b/b-wt0", {"target": 3.0}),
                                                                       worktree("/t/b/b-wt1", {"target": 2.0})]}},
             {"name": "alpha", "disk": {"size_gb": 300.0, "worktrees": [worktree("/t/a/a-wt0", dict(WRAP_PARTS))] + [
                 worktree(f"/t/a/a-wt{n}", {"target": 1.0}) for n in range(1, 6)]}},
             {"name": "gamma", "disk": None}]
    largest = [{"path": f"/t/a/a-wt{n}", "part": "target", "size_gb": 9.0 - n} for n in range(3)]
    return teams, {"volume": {"free_gb": 300.0}, "builds": {"largest": largest}, "disk_at": NOW - 600}


def cells(row):
    """Each cell of a row as (character, colour), so two rows compare equal only in text and colour alike."""
    return [(ch, colour) for text, colour in row for ch in text]


class RenderDiskEveryTeamTests(RenderCase):
    """deck-fixes item 3: DISK lists every team of the snapshot and, at a fixed height, fits the room left for it."""

    def test_an_unmeasured_team_follows_the_measured_ones_as_not_measured_yet(self):
        rows = self.rows()
        box = self.box(rows, "DISK")
        text = "\n".join(t for _, t, _ in box)
        self.assertInOrder(text, "gamma", "95.0G", "alpha", "80.0G", "beta", "not measured yet")
        row, line, x0 = self.line(box, "beta")
        self.assertEqual(line.index("beta"), self.line(box, "gamma")[1].index("gamma"), text)
        self.assertWord(colour_of(row, "not measured yet", x0), "dim", "not measured yet")
        self.assertEqual(sorted(disk_blocks(box_bodies(self.texts(), "DISK"))), ["wt", "wt2"], text)

    def test_disk_shows_every_team_as_not_measured_yet_when_none_is_measured(self):
        snap = copy.deepcopy(self.snap)
        for t in snap["teams"]:
            t["disk"] = None
        snap["builds"]["largest"] = []
        snap["disk_at"] = None
        texts = self.texts(snap)
        self.assertTrue(has_box(texts, "DISK"), "\n".join(texts))
        bodies = box_bodies(texts, "DISK")
        self.assertEqual(disk_names(bodies), ["alpha", "beta", "gamma"], bodies)
        self.assertEqual(len(bodies), 3, bodies)
        self.assertEqual([b for b in bodies if "not measured yet" not in b], [], bodies)
        self.assertInOrder(texts[find_box(texts, "DISK")[0]], "DISK", "300G free", "? ago")

    def test_at_a_fixed_height_disk_fits_the_room_left_team_rows_last_and_without_one_every_worktree_shows(self):
        snap = disk_fleet_snapshot()
        whole = [f"{p} {DISK_PARTS[p]:.1f}G" for p in sorted(DISK_PARTS, key=lambda p: -DISK_PARTS[p])]
        texts = self.texts(snap, 120, height=60)
        self.assertTrue(has_box(texts, "DISK"), "\n".join(texts))
        bodies = box_bodies(texts, "DISK")
        self.assertEqual(disk_names(bodies), list(DISK_TEAMS), bodies)
        self.assertEqual([b for b in bodies if re.search(r"\+\d", b)], [], "no +n on a DISK row")
        self.assertEqual({tail: parts for tail, (_, parts) in disk_blocks(bodies).items() if parts != whole}, {},
                         "a worktree is whole or left out")
        # The room DISK has at each height, measured from the screen: the panels above it keep today's layout.
        rooms = {}
        for height in range(60, 20, -1):
            texts = self.texts(snap, 120, height=height)
            self.assertEqual(len(texts), height)
            rooms[disk_room(texts)] = texts
            if min(rooms) < 9:
                break
        # Ten rows hold the 8 team rows and the borders and nothing more; nine cannot hold them.
        self.assertIn(10, rooms)
        self.assertIn(9, rooms)
        bodies = box_bodies(rooms[10], "DISK")
        self.assertEqual(bodies, [b for b in bodies if not b.startswith(" ")], "no worktree rows")
        self.assertEqual(disk_names(bodies), list(DISK_TEAMS), bodies)
        self.assertEqual(len(bodies), len(DISK_TEAMS), bodies)
        self.assertFalse(has_box(rooms[9], "DISK"), "\n".join(rooms[9]))
        tails = {f"{name[:5]}-wt{n}" for name in DISK_TEAMS for n in range(5)}
        blocks = disk_blocks(box_bodies(self.texts(snap, 120), "DISK"))
        self.assertEqual(set(blocks), tails)
        self.assertEqual({tail: parts for tail, (_, parts) in blocks.items() if parts != whole}, {})

    def test_disk_takes_the_first_layout_that_fits_the_room_k_5_to_1_then_largest_cut_then_team_rows(self):
        # alpha (300G) has 6 worktrees, a-wt0 wrapped over 5 rows and the rest one row each; beta (200G) has 2
        # one-row worktrees; gamma is not measured. Rows with borders: k=5 19, k=4 18, k=3 17, k=2 16, k=1 14;
        # then k=1 with 2, 1, 0 largest rows at 13, 12, 11; team rows only from 10 down to 5; nothing below.
        teams, snap = disk_order_fixture()
        alpha = [f"a-wt{n}" for n in range(5)]
        beta = ["b-wt0", "b-wt1"]
        wrapped = [f"{p} {WRAP_PARTS[p]:.1f}G" for p in sorted(WRAP_PARTS, key=lambda p: -WRAP_PARTS[p])]
        largest = [f"largest {9.0 - n:.1f}G target a-wt{n}" for n in range(3)]
        expected = {19: (5, 2, 3), 18: (4, 2, 3), 17: (3, 2, 3), 16: (2, 2, 3), 15: (1, 1, 3), 14: (1, 1, 3),
                    13: (1, 1, 2), 12: (1, 1, 1), 11: (1, 1, 0), **{room: (0, 0, 0) for room in range(5, 11)}}
        for room in [float("inf"), 40, 20, *range(19, -1, -1)]:
            with self.subTest(room=room):
                texts = [row_text(row) for row in self.r._disk(teams, snap, NOW, 53, room)]
                if room < 5:
                    self.assertEqual(texts, [])
                    continue
                k_alpha, k_beta, n_largest = expected.get(room, (5, 2, 3))
                self.assertLessEqual(len(texts), room)
                bodies = box_bodies(texts, "DISK")
                self.assertEqual(disk_names(bodies), ["alpha", "beta", "gamma"], bodies)
                blocks = disk_blocks(bodies)
                self.assertEqual(list(blocks), alpha[:k_alpha] + beta[:k_beta], bodies)
                if k_alpha:
                    self.assertEqual(blocks["a-wt0"][1], wrapped, "a wrapped worktree keeps every part row")
                self.assertEqual([b for b in bodies if b.startswith("largest")], largest[:n_largest], bodies)
                self.assertEqual(len(texts), 3 + k_alpha + 4 * (k_alpha > 0) + k_beta + n_largest + 2, bodies)

    def test_disk_fitting_its_room_leaves_the_focus_agents_builds_and_log_as_they_are_without_worktrees(self):
        snap = disk_fleet_snapshot()
        snap["builds"]["queue"] = render_queue()
        snap["teams"][0]["sessions"][0]["agents"] = [render_agent("a1"), render_agent("a2", started=NOW - 300)]
        bare = copy.deepcopy(snap)
        for t in bare["teams"]:
            t["disk"]["worktrees"] = []
        shown = {}
        # The floor of 52 leaves DISK room under the focus box's tools and turns rows (deck-motion B3-B5).
        for height in range(200, 51, -2):
            with self.subTest(height=height):
                rows, bare_rows = self.rows(snap, 120, height=height), self.rows(bare, 120, height=height)
                texts = [row_text(row) for row in rows]
                for title in ("Opus 5.5 · acme-s0", "BUILDS · queue", "log · acme", "DISK"):
                    self.assertTrue(has_box(texts, title), f"{title}\n" + "\n".join(texts))
                self.assertTrue([t for t in texts if "agents · 2 running" in t], "\n".join(texts))
                log_bottom = box_span(texts, "log · ")[1]
                self.assertEqual([cells(row) for row in rows[:log_bottom + 1]],
                                 [cells(row) for row in bare_rows[:log_bottom + 1]])
                # The team column beside DISK, down to the bare screen's key line (a screen ends where its
                # columns end, so the bare one is shorter where DISK was the longer column).
                end = min(len(rows), len(bare_rows)) - 1
                self.assertEqual([cells(row)[:66] for row in rows[:end]],
                                 [cells(row)[:66] for row in bare_rows[:end]])
                shown[height] = len(disk_blocks(box_bodies(texts, "DISK")))
        # Not vacuous: the worktree screens differ from the bare ones in DISK, all 40 worktrees at the tallest
        # heights and fewer, then none, as the room shrinks.
        self.assertEqual(shown[200], 40, shown)
        self.assertIn(0, shown.values(), shown)
        self.assertTrue([n for n in shown.values() if 0 < n < 40], shown)


class RenderFleetTitleTests(RenderCase):
    """deck-fixes item 5: the FLEET title counts teams in the singular for one."""

    def test_one_team_is_1_team_and_three_are_3_teams(self):
        texts = self.texts(team_filter="alpha")
        top = texts[find_box(texts, "FLEET")[0]]
        self.assertIn("FLEET · 1 team ", top)
        self.assertNotIn("1 teams", top)
        texts = self.texts()
        self.assertIn("FLEET · 3 teams ", texts[find_box(texts, "FLEET")[0]])


def broadcast_snapshot():
    """The big-team shape of item 6 on render_snapshot: alpha has 289 waiting, 287 of them broadcasts. Sess-A waits on
    14, 12 of them broadcasts, its mail 5m old and its oldest message 2h30m; Sess-B waits on 12 broadcasts only."""
    snap = render_snapshot()
    alpha = a_team(snap, "alpha")
    alpha.update(mail_waiting=289, broadcasts_waiting=287)
    alpha["sessions"] = [
        render_session("alpha", "sa", "Sess-A", "lane",
                       mail={"waiting": 14, "broadcasts": 12, "held": 0, "delivered_today": 4,
                             "oldest_mail_s": 300, "oldest_waiting_s": 9000}),
        render_session("alpha", "sb", "Sess-B", "lane",
                       mail={"waiting": 12, "broadcasts": 12, "held": 0, "delivered_today": 4,
                             "oldest_mail_s": None, "oldest_waiting_s": 9000})]
    return snap


class RenderBroadcastTests(RenderCase):
    """deck-fixes item 6, render half: undelivered broadcasts show as `◎n` apart from mail."""

    def setUp(self):
        super().setUp()
        self.big = broadcast_snapshot()

    def test_fleet_shows_mail_without_the_broadcasts_and_the_broadcasts_as_a_ring(self):
        fleet = self.box_text(self.rows(self.big), "FLEET")
        self.assertRegex(fleet, r"✉2(?!\d)")
        self.assertIn("◎287", fleet)
        self.assertNotIn("✉289", fleet)

    def test_the_team_box_shows_mail_and_broadcasts_apart(self):
        _, line, _ = self.line(self.box(self.rows(self.big), "alpha · 2 sessions"), "lanes")
        self.assertRegex(line, r"✉ 2(?!\d)")
        self.assertInOrder(line, "lanes", "✉ 2", "◎ 287", "today")
        self.assertNotIn("289", line)

    def test_a_session_badge_is_its_mail_with_the_mail_age_or_else_its_broadcasts(self):
        box = self.box(self.rows(self.big), "alpha · 2 sessions")
        _, line, _ = self.line(box, "Sess-A")
        self.assertIn("✉2 5m", line)
        _, line, _ = self.line(box, "Sess-B")
        self.assertIn("◎12", line)
        self.assertNotIn("✉", line)

    def test_the_focus_box_shows_the_mail_count_and_the_broadcasts(self):
        focus = self.box_text(self.rows(self.big, cursor=1), "Opus 5.5 · Sess-B")
        self.assertIn("✉ 0 waiting", focus)
        self.assertIn("◎ 12 broadcasts", focus)

    def test_a_snapshot_without_broadcast_fields_shows_no_ring(self):
        for width in sorted({30, 80, 120, 180, *BUDGET_WIDTHS}):
            for cursor in range(4):
                with self.subTest(width=width, cursor=cursor):
                    screen = self.screen(width=width, cursor=cursor)
                    self.assertNotIn("◎", screen)

    def test_the_big_team_shape_keeps_every_row_within_the_width_and_every_box_whole(self):
        for width in sorted({30, 80, 120, 180, *BUDGET_WIDTHS}):
            for cursor in (0, 1):
                with self.subTest(width=width, cursor=cursor):
                    texts = self.texts(self.big, width, cursor=cursor)
                    self.assertEqual([t for t in texts if len(t) > width], [])
                    self.assertEqual(broken_boxes(texts), [])
                    self.assertIn("◎287", "\n".join(box_bodies(texts, "FLEET")))


def status_row(sid, ts, used, cost, cwd):
    """A status-line record of session sid with its context use and its cost so far, written from folder cwd."""
    raw = {"session_id": sid, "cwd": str(cwd), "context_window": {"used_percentage": used,
                                                                  "context_window_size": 1000000},
           "cost": {"total_cost_usd": cost}, "model": {"id": "claude-opus"}}
    return {"ts": iso(ts), "session_id": sid, "cwd": str(cwd), "raw": raw}


def orc_team(root, repo_name="repo-tessa"):
    """Team tessa with the orchestrator (sid-orc, launched in root/<repo_name>) and lane a (sid-a), both working in
    herdr. Returns (the folders collect() reads, the team's v2 folder, the orchestrator's launch folder)."""
    folders = {name: root / name for name in ("teams", "projects", "metrics")}
    queue = root / "run" / "queue"
    for folder in (*folders.values(), queue):
        folder.mkdir(parents=True)
    repo = root / repo_name
    write_manifest(folders["teams"] / "tessa.toml", "tessa", root / "team-tessa", repo)
    home = root / "team-tessa" / "team"
    (home / "v2" / "launch").mkdir(parents=True)
    (home / "team.json").write_text(json.dumps({"product": "tessa", "lanes": {"a": {"path": "."}}}))
    (home / "v2" / "state.json").write_text(json.dumps({
        "orc": {"status": "working", "state_since": NOW - 600, "sid": "sid-orc"},
        "a": {"status": "working", "state_since": NOW - 600, "sid": "sid-a"}}))
    (folders["projects"] / "-tessa").mkdir()
    return ({"teams_dir": folders["teams"], "projects_dir": folders["projects"], "metrics_dir": folders["metrics"],
             "queue_dir": queue}, home / "v2", repo)


def orc_team_snapshot(collect, dirs):
    herdr = ReadOnlyHerdr(
        agents=[{"pane_id": "p-orc", "name": "tessa-orc", "agent_status": "working"},
                {"pane_id": "p-a", "name": "tessa-a", "agent_status": "working"}],
        panes=[{"pane_id": "p-orc", "label": "tessa-orc"}, {"pane_id": "p-a", "label": "tessa-a"}])
    return collect.collect(now=NOW, herdr=herdr, ps_text="", **dirs)


class SessionMetricsCwdTests(unittest.TestCase):
    """A session's status-line record is also looked for in the log named for the folder its transcript's last
    record names: the orchestrator is launched in alpha-launch and has since moved to elsewhere."""

    def setUp(self):
        from codeteam2.deck import collect
        self.c = collect
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.dirs, _, self.launch = orc_team(self.root, "alpha-launch")
        self.elsewhere = self.root / "elsewhere"
        self.metrics = self.dirs["metrics_dir"]

    def transcript(self, last_cwd):
        """The orchestrator's transcript: its first record written in the launch folder, its last in last_cwd
        (no cwd at all when last_cwd is None)."""
        last = {"type": "assistant", "timestamp": iso(NOW - 100),
                "message": {"content": [{"type": "text", "text": "ok"}]}}
        if last_cwd is not None:
            last["cwd"] = str(last_cwd)
        first = {"type": "user", "timestamp": iso(NOW - 200), "message": {"content": "[codeteam] hi"}}
        if last_cwd is not None:
            first["cwd"] = str(self.launch)
        write_jsonl(self.dirs["projects_dir"] / "-tessa" / "sid-orc.jsonl", [first, last])

    def orc(self):
        team = orc_team_snapshot(self.c, self.dirs)["teams"][0]
        return next(s for s in team["sessions"] if s["key"] == "orc")

    def cells(self, row):
        return (row.get("context") or {}).get("used_pct"), (row.get("cost") or {}).get("session_usd")

    def test_a_record_only_in_the_log_of_the_transcripts_cwd_gives_the_context_and_cost(self):
        write_jsonl(self.metrics / "alpha-launch.jsonl", [status_row("sid-other", NOW - 60, 77, 7.0, self.launch)])
        write_jsonl(self.metrics / "elsewhere.jsonl", [status_row("sid-orc", NOW - 60, 19, 19.31, self.elsewhere)])
        self.transcript(self.elsewhere)
        self.assertEqual(self.cells(self.orc()), (19, 19.31))

    def test_a_newer_record_in_the_transcripts_cwd_log_wins_over_an_older_one_in_the_launch_log(self):
        write_jsonl(self.metrics / "alpha-launch.jsonl", [status_row("sid-orc", NOW - 600, 30, 5.0, self.launch)])
        write_jsonl(self.metrics / "elsewhere.jsonl", [status_row("sid-orc", NOW - 60, 19, 19.31, self.elsewhere)])
        self.transcript(self.elsewhere)
        self.assertEqual(self.cells(self.orc()), (19, 19.31))

    def test_a_transcript_without_a_cwd_takes_the_launch_logs_record_as_before(self):
        # Passes on the old code too: it guards today's behaviour, which the change must keep.
        write_jsonl(self.metrics / "alpha-launch.jsonl", [status_row("sid-orc", NOW - 600, 30, 5.0, self.launch)])
        write_jsonl(self.metrics / "elsewhere.jsonl", [status_row("sid-orc", NOW - 60, 19, 19.31, self.elsewhere)])
        self.transcript(None)
        self.assertEqual(self.cells(self.orc()), (30, 5.0))

    def seat(self, row):
        return (row.get("cost") or {}).get("seat_today_usd")

    def test_a_win_in_the_transcripts_cwd_log_counts_seat_cost_under_that_cwd(self):
        # No .git anywhere: the cwd is its own root. 19.31 + 2.0 are under elsewhere; 100.0 is under the launch
        # folder and would be the sum if the launch root were used.
        write_jsonl(self.metrics / "elsewhere.jsonl", [
            status_row("sid-orc", NOW - 60, 19, 19.31, self.elsewhere),
            status_row("sid-x", NOW - 120, 5, 2.0, self.elsewhere / "sub"),
            status_row("sid-y", NOW - 120, 5, 100.0, self.launch)])
        self.transcript(self.elsewhere)
        row = self.orc()
        self.assertEqual(self.cells(row), (19, 19.31))
        self.assertAlmostEqual(self.seat(row), 21.31)

    def test_a_win_in_the_log_of_a_cwd_inside_a_worktree_counts_seat_cost_under_that_worktrees_root(self):
        # The transcript's cwd is elsewhere/sub inside the worktree elsewhere: the record is in sub.jsonl and seat
        # cost covers elsewhere (19.31 + 2.0), not only elsewhere/sub (19.31), nor the launch folder's 100.0.
        (self.elsewhere / "sub").mkdir(parents=True)
        (self.elsewhere / ".git").mkdir()
        write_jsonl(self.metrics / "sub.jsonl", [
            status_row("sid-orc", NOW - 60, 19, 19.31, self.elsewhere / "sub"),
            status_row("sid-x", NOW - 120, 5, 2.0, self.elsewhere / "other"),
            status_row("sid-y", NOW - 120, 5, 100.0, self.launch)])
        self.transcript(self.elsewhere / "sub")
        row = self.orc()
        self.assertEqual(self.cells(row), (19, 19.31))
        self.assertAlmostEqual(self.seat(row), 21.31)

    def test_a_win_in_the_launch_log_counts_seat_cost_under_the_launch_folder(self):
        # The launch log's record is newer, so it wins; 30.0 + 4.0 are under the launch folder, and 50.0 (under
        # elsewhere) would be counted if the transcript cwd's root were used.
        write_jsonl(self.metrics / "alpha-launch.jsonl", [
            status_row("sid-orc", NOW - 60, 30, 30.0, self.launch),
            status_row("sid-p", NOW - 120, 5, 4.0, self.launch / "sub"),
            status_row("sid-q", NOW - 120, 5, 50.0, self.elsewhere)])
        write_jsonl(self.metrics / "elsewhere.jsonl", [status_row("sid-orc", NOW - 600, 19, 19.31, self.elsewhere)])
        self.transcript(self.elsewhere)
        row = self.orc()
        self.assertEqual(self.cells(row), (30, 30.0))
        self.assertAlmostEqual(self.seat(row), 34.0)

    def test_a_timestamp_tie_takes_the_launch_logs_record(self):
        write_jsonl(self.metrics / "alpha-launch.jsonl", [status_row("sid-orc", NOW - 60, 30, 5.0, self.launch)])
        write_jsonl(self.metrics / "elsewhere.jsonl", [status_row("sid-orc", NOW - 60, 19, 19.31, self.elsewhere)])
        self.transcript(self.elsewhere)
        self.assertEqual(self.cells(self.orc()), (30, 5.0))

    def test_an_undated_record_in_the_launch_log_loses_to_a_dated_one_in_the_transcripts_cwd_log(self):
        undated = status_row("sid-orc", NOW - 60, 30, 5.0, self.launch)
        del undated["ts"]
        write_jsonl(self.metrics / "alpha-launch.jsonl", [undated])
        write_jsonl(self.metrics / "elsewhere.jsonl", [status_row("sid-orc", NOW - 600, 19, 19.31, self.elsewhere)])
        self.transcript(self.elsewhere)
        self.assertEqual(self.cells(self.orc()), (19, 19.31))


class BroadcastCollectTests(unittest.TestCase):
    """Waiting broadcasts (a RULING, or a message to `all` in any case) counted apart from mail, in
    the big-team shape made small: a RULING to all fanned out to a, b and c (a's copy held), a NOTE to ALL for b, and
    for the orchestrator a RULING 90 minutes old and two REQUESTs 30 and 20 minutes old. Every existing count
    still covers every waiting message."""

    def setUp(self):
        from codeteam2.deck import collect
        from codeteam2.store import Store
        self.c = collect
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dirs, v2, _ = orc_team(Path(tmp.name))
        self.db = v2 / "messages.db"
        store = Store(self.db)

        def put(ts, kind, recipient, target, state="queued"):
            mid = store.add("general", "Orc-Tessa", kind, recipient, target, "a note")
            store.db.execute("UPDATE messages SET ts=?, state=?, delivered_at=? WHERE id=?",
                             (iso(ts), state, iso(ts) if state == "delivered" else None, mid))

        put(NOW - 4 * HOUR, "RULING", "all", "c", state="delivered")
        for target, state in (("a", "held"), ("b", "queued"), ("c", "queued")):
            put(NOW - 3 * HOUR, "RULING", "all", target, state=state)
        put(NOW - 2 * HOUR, "NOTE", "ALL", "b")
        put(NOW - 90 * MIN, "RULING", "Orc-Tessa", "orc")
        put(NOW - 30 * MIN, "REQUEST", "Orc-Tessa", "orc")
        put(NOW - 20 * MIN, "REQUEST", "Orc-Tessa", "orc")
        store.db.close()

    def test_read_messages_counts_the_waiting_broadcasts_and_each_targets_oldest_mail(self):
        m = self.c.read_messages(self.db, NOW)
        self.assertEqual((m["queued"], m["held"]), (6, 1))
        orc = m["by_target"]["orc"]
        self.assertEqual(orc["waiting"], 3)
        self.assertEqual(epoch(orc["oldest_waiting_ts"]), NOW - 90 * MIN)
        self.assertEqual(m.get("broadcasts_waiting"), 5)
        self.assertEqual(orc.get("broadcasts"), 1)
        self.assertEqual(m["by_target"]["b"].get("broadcasts"), 2)
        self.assertEqual(epoch(orc.get("oldest_mail_ts") or iso(0)), NOW - 30 * MIN)
        self.assertIsNone(m["by_target"]["a"].get("oldest_mail_ts"))

    def test_the_team_row_counts_the_broadcasts_apart_and_mail_waiting_stays_the_total(self):
        team = orc_team_snapshot(self.c, self.dirs)["teams"][0]
        self.assertEqual(team["mail_waiting"], 7)
        self.assertEqual(team["messages"]["held"], 1)
        self.assertEqual(team.get("broadcasts_waiting"), 5)

    def test_a_sessions_mail_cell_gives_its_broadcasts_and_the_age_of_its_oldest_mail(self):
        sessions = {s["key"]: s for s in orc_team_snapshot(self.c, self.dirs)["teams"][0]["sessions"]}
        orc, lane = sessions["orc"]["mail"], sessions["a"]["mail"]
        self.assertEqual((orc["waiting"], orc["held"], orc["oldest_waiting_s"]), (3, 0, 90 * MIN))
        self.assertEqual((lane["waiting"], lane["held"]), (1, 1))
        self.assertEqual(orc.get("broadcasts"), 1)
        self.assertEqual(orc.get("oldest_mail_s"), 30 * MIN)
        self.assertEqual(lane.get("broadcasts"), 1)
        self.assertIsNone(lane.get("oldest_mail_s"))


if __name__ == "__main__":
    unittest.main()
