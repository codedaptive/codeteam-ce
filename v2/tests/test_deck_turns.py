"""SPEC-deck-motion B3-B5 in collect.py: the tool trace, the per-turn output tokens and the turns-left estimate,
as functions over transcript records and as keys of collect()'s session row.

A turn from turn_stats is {"output": tokens, "context": tokens}; a compaction is {"compacted": True}."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import test_deck  # noqa: E402
from test_deck import NOW, ReadOnlyHerdr, silent_lane_fixture, write_jsonl  # noqa: E402

BOUNDARY = {"type": "system", "subtype": "compact_boundary"}
NEW_ROW_KEYS = {"turns", "turns_left"}
NEW_RECENT_KEYS = {"trace"}


def user(text="go"):
    return {"type": "user", "message": {"role": "user", "content": text}}


def user_blocks(*blocks):
    return {"type": "user", "message": {"role": "user", "content": list(blocks)}}


def tool_result(tool_id="t"):
    return {"type": "tool_result", "tool_use_id": tool_id, "content": "ok"}


def text(words="ok"):
    return {"type": "text", "text": words}


def assistant(mid, out=0, inp=0, read=0, create=0, tools=()):
    blocks = [{"type": "tool_use", "id": f"{mid}-{name}", "name": name, "input": {}} for name in tools] or [text()]
    usage = {"input_tokens": inp, "cache_read_input_tokens": read, "cache_creation_input_tokens": create,
             "output_tokens": out}
    return {"type": "assistant", "message": {"id": mid, "role": "assistant", "content": blocks, "usage": usage}}


def meta_user(content="Base directory for this skill: /x"):
    """What Claude Code writes mid-turn when a skill loads."""
    return {"type": "user", "isMeta": True, "message": {"role": "user", "content": content}}


def synthetic(mid):
    """What Claude Code writes on an API error: an assistant record of model <synthetic> with all-zero usage."""
    rec = assistant(mid)
    rec["message"]["model"] = "<synthetic>"
    rec["message"]["content"] = [text("API Error: overloaded")]
    return rec


def outputs(entries):
    return [e if e.get("compacted") else e["output"] for e in entries]


def records_with_contexts(*contexts):
    """One turn per context size (its input tokens); "C" is a compaction between turns."""
    records = []
    for i, ctx in enumerate(contexts):
        if ctx == "C":
            records.append(BOUNDARY)
        else:
            records += [user(), assistant(f"m{i}", out=1, inp=ctx)]
    return records


class TurnsCase(unittest.TestCase):
    def setUp(self):
        from codeteam2.deck import collect
        self.c = collect

    def turns(self, *contexts):
        return self.c.turn_stats(records_with_contexts(*contexts))


class RecentTraceTests(TurnsCase):
    def test_the_last_twelve_tool_names_oldest_first(self):
        records = [assistant(f"m{i}", tools=(f"tool{i}",)) for i in range(15)]
        self.assertEqual(self.c.recent_trace(records), [f"tool{i}" for i in range(3, 15)])

    def test_fewer_than_twelve_are_all_given_in_order_from_assistant_records_only(self):
        records = [user(), assistant("m1", tools=("Read", "Grep")), user_blocks(tool_result()),
                   {"type": "user", "message": {"content": [{"type": "tool_use", "name": "NotMine"}]}},
                   assistant("m2", tools=("Edit",))]
        self.assertEqual(self.c.recent_trace(records), ["Read", "Grep", "Edit"])

    def test_n_bounds_the_trace(self):
        records = [assistant("m1", tools=("Read", "Grep", "Edit", "Bash"))]
        self.assertEqual(self.c.recent_trace(records, n=2), ["Edit", "Bash"])

    def test_no_tool_calls_give_an_empty_trace(self):
        self.assertEqual(self.c.recent_trace([user(), assistant("m1")]), [])
        self.assertEqual(self.c.recent_trace([]), [])


class TurnStatsTests(TurnsCase):
    def test_a_tool_result_continues_the_turn_and_a_prompt_starts_one(self):
        records = [user(), assistant("m1", out=10, tools=("Read",)), user_blocks(tool_result()),
                   assistant("m2", out=20), user("next"), assistant("m3", out=5)]
        self.assertEqual(outputs(self.c.turn_stats(records)), [30, 5])

    def test_a_user_record_with_text_beside_tool_results_starts_a_turn(self):
        records = [user(), assistant("m1", out=10), user_blocks(tool_result(), text("and also")),
                   assistant("m2", out=4), user_blocks(text("plain blocks")), assistant("m3", out=2)]
        self.assertEqual(outputs(self.c.turn_stats(records)), [10, 4, 2])

    def test_a_message_id_repeated_across_records_is_counted_once(self):
        records = [user(), assistant("m1", out=40, tools=("Read",)), assistant("m1", out=40, tools=("Edit",)),
                   assistant("m2", out=2)]
        self.assertEqual(outputs(self.c.turn_stats(records)), [42])

    def test_context_is_input_plus_cache_read_plus_cache_creation_of_the_last_usage(self):
        records = [user(), assistant("m1", out=1, inp=10, read=1000, create=5),
                   user_blocks(tool_result()), assistant("m2", out=1, inp=20, read=2000, create=30)]
        self.assertEqual([t["context"] for t in self.c.turn_stats(records)], [2050])

    def test_a_compaction_is_an_entry_in_sequence(self):
        records = [user(), assistant("m1", out=3), BOUNDARY, user(), assistant("m2", out=4)]
        entries = self.c.turn_stats(records)
        self.assertEqual(outputs(entries), [3, {"compacted": True}, 4])
        self.assertEqual(entries[1], {"compacted": True})

    def test_only_the_last_twelve_entries_compactions_included(self):
        records = []
        for i in range(1, 14):
            records += [user(), assistant(f"m{i}", out=i)]
            if i == 10:
                records.append(BOUNDARY)
        want = [3, 4, 5, 6, 7, 8, 9, 10, {"compacted": True}, 11, 12, 13]
        self.assertEqual(outputs(self.c.turn_stats(records)), want)

    def test_records_without_usage_are_tolerated(self):
        bare = {"type": "assistant", "message": {"role": "assistant", "content": [text()]}}
        records = [user(), bare, assistant("m2", out=6), user("next"), bare, {"type": "assistant"}]
        entries = self.c.turn_stats(records)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["output"], 6)

    def test_no_records_give_no_turns(self):
        self.assertEqual(self.c.turn_stats([]), [])

    def test_a_meta_user_record_continues_the_turn(self):
        records = [user(), assistant("m1", out=10), meta_user(), assistant("m2", out=5),
                   meta_user([text("skill body")]), assistant("m3", out=1), user("next"), assistant("m4", out=2)]
        self.assertEqual(outputs(self.c.turn_stats(records)), [16, 2])

    def test_a_synthetic_reply_is_not_the_turns_last_usage(self):
        records = [user(), assistant("m1", out=10, inp=5000, read=40000), synthetic("s1")]
        entries = self.c.turn_stats(records)
        self.assertEqual([(t["output"], t["context"]) for t in entries], [(10, 45000)])

    def test_a_turn_answered_only_by_synthetic_replies_is_not_listed(self):
        records = [user(), assistant("m1", out=3), user("retry"), synthetic("s1"), synthetic("s2"),
                   user("again"), assistant("m2", out=4)]
        self.assertEqual(outputs(self.c.turn_stats(records)), [3, 4])


class TurnsLeftTests(TurnsCase):
    def test_window_less_context_over_the_mean_growth(self):
        self.assertEqual(self.c.turns_left(self.turns(100000, 110000, 120000, 130000), 200000), 7)

    def test_the_estimate_is_rounded_down(self):
        self.assertEqual(self.c.turns_left(self.turns(100000, 103000), 200000), 32)

    def test_growth_is_read_over_the_last_five_turns_only(self):
        turns = self.turns(10000, 50000, 100000, 110000, 120000, 130000, 140000)
        self.assertEqual(self.c.turns_left(turns, 200000), 6)

    def test_growth_is_read_after_the_last_compaction(self):
        turns = self.turns(100000, 150000, "C", 20000, 30000, 40000)
        self.assertEqual(self.c.turns_left(turns, 200000), 16)

    def test_fewer_than_two_turns_since_the_compaction_give_none(self):
        self.assertIsNone(self.c.turns_left(self.turns(100000, 150000, "C", 20000), 200000))
        self.assertIsNone(self.c.turns_left(self.turns(100000), 200000))
        self.assertIsNone(self.c.turns_left([], 200000))

    def test_no_growth_gives_none(self):
        self.assertIsNone(self.c.turns_left(self.turns(50000, 50000, 50000), 200000))
        self.assertIsNone(self.c.turns_left(self.turns(60000, 50000, 40000), 200000))

    def test_no_window_gives_none(self):
        self.assertIsNone(self.c.turns_left(self.turns(100000, 110000, 120000), None))

    def test_context_past_the_window_gives_zero(self):
        self.assertEqual(self.c.turns_left(self.turns(180000, 195000, 210000), 200000), 0)

    def test_a_synthetic_reply_leaves_the_estimate_standing(self):
        records = records_with_contexts(100000, 110000, 120000) + [synthetic("s1"), user("retry"), synthetic("s2")]
        self.assertEqual(self.c.turns_left(self.c.turn_stats(records), 200000), 8)


# Expected nonvolatile Orc-Tessa fields from IntegrationTests' fixture; cwd, transcript_mtime and the mail's time
# depend on the temporary folder and clock, so they are checked separately.
BEFORE_ORC = {
    "agent": "tessa-orc", "agents": [], "api_error": None,
    "cache": {"expires_in_s": 1200.0, "hit_ratio": 0.9, "warm": True},
    "context": {"compactions": 0, "compactions_partial": False, "used_pct": 42.0, "window": 1000000},
    "cost": {"seat_today_partial": False, "seat_today_usd": 3.2, "session_usd": 3.2},
    "draft_since": None, "effort": "high",
    "flags": {"api_error": False, "between_turns": True, "blocked": False, "blocked_for_s": None, "held": False,
              "typing": False, "waiting_on_finished_child": False},
    "herdr": {"since": NOW - 600, "status": "working"}, "idle_exit_in_s": None, "key": "orc",
    "mail": {"broadcasts": 0, "delivered_today": 0, "held": 0, "oldest_mail_s": None, "oldest_waiting_s": None,
             "waiting": 0},
    "model": "claude-opus", "name": "Orc-Tessa", "role": "orc", "sid": "sid-orc", "team": "tessa",
    "transcript_state": "ended", "worktree": None}
BEFORE_ORC_RECENT = {"tools": [],
                     "messages": [{"dir": "out", "kind": "REQUEST", "peer": "Coord-a", "text": "check the dialog"}]}
VOLATILE = {"cwd", "transcript_mtime", "recent"}


class SessionRowExistingKeysTests(unittest.TestCase):
    """Check Orc-Tessa's expected fields and the trace, turns and turns-left fields in IntegrationTests' fixture."""

    def setUp(self):
        fixture = test_deck.IntegrationTests("test_snapshot_is_json_and_lists_the_codeteam2_team_with_its_sessions")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.orc = fixture._session(fixture._team("tessa"), "Orc-Tessa")

    def test_the_row_gains_the_trace_turns_and_turns_left(self):
        self.assertTrue(NEW_ROW_KEYS <= set(self.orc), sorted(self.orc))
        self.assertTrue(NEW_RECENT_KEYS <= set(self.orc["recent"]), sorted(self.orc["recent"]))
        self.assertEqual(self.orc["recent"]["trace"], [])
        self.assertTrue(all(type(t) is int or t == {"compacted": True} for t in self.orc["turns"]), self.orc["turns"])
        self.assertIsNone(self.orc["turns_left"])

    def test_every_existing_key_keeps_its_value(self):
        self.assertEqual(set(self.orc) - NEW_ROW_KEYS, set(BEFORE_ORC) | VOLATILE)
        self.assertEqual({k: self.orc[k] for k in BEFORE_ORC}, BEFORE_ORC)
        self.assertTrue(self.orc["cwd"].endswith("/repo-tessa"), self.orc["cwd"])
        self.assertIsInstance(self.orc["transcript_mtime"], float)
        recent = self.orc["recent"]
        self.assertEqual(set(recent) - NEW_RECENT_KEYS, set(BEFORE_ORC_RECENT))
        self.assertEqual(recent["tools"], BEFORE_ORC_RECENT["tools"])
        self.assertEqual([{k: v for k, v in m.items() if k != "ts"} for m in recent["messages"]],
                         BEFORE_ORC_RECENT["messages"])


class SessionRowTurnsTests(unittest.TestCase):
    """collect() over silent_lane_fixture with the lane's transcript and status-line log replaced."""

    def setUp(self):
        from codeteam2.deck import collect
        self.c = collect
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.folders = silent_lane_fixture(self.root, self.root / "wt")
        self.transcript = self.folders["projects_dir"] / "-tessa" / "sid-a.jsonl"

    def row(self, records, window=200000):
        write_jsonl(self.transcript, records)
        cwd = self.root / "team-tessa" / "workcrews" / "a" / "tessa-exchange-a"
        write_jsonl(self.folders["metrics_dir"] / f"{cwd.name}.jsonl", [{
            "ts": test_deck.iso(NOW - 60), "session_id": "sid-a", "cwd": str(cwd),
            "raw": {"session_id": "sid-a", "context_window": {"used_percentage": 10.0,
                                                              "context_window_size": window}}}])
        herdr = ReadOnlyHerdr(agents=[{"pane_id": "p-a", "name": "tessa-a", "agent_status": "working"}],
                              panes=[{"pane_id": "p-a", "label": "tessa-a"}])
        snap = self.c.collect(now=NOW, herdr=herdr, ps_text="", **self.folders)
        json.dumps(snap)
        return snap["teams"][0]["sessions"][0]

    def test_the_row_carries_the_trace_and_the_turns_with_their_compaction(self):
        s = self.row([user(), assistant("m1", out=100, tools=("Read",)), assistant("m1", out=100, tools=("Edit",)),
                      user_blocks(tool_result()), assistant("m2", out=30), BOUNDARY,
                      user("next"), assistant("m3", out=7, tools=("Bash",))])
        self.assertEqual(s.get("recent", {}).get("trace"), ["Read", "Edit", "Bash"])
        self.assertEqual(s.get("turns"), [130, {"compacted": True}, 7])

    def test_turns_left_uses_the_status_line_window(self):
        records = records_with_contexts(100000, 110000, 120000)
        self.assertEqual(self.row(records, window=200000).get("turns_left"), 8)

    def test_only_turns_in_the_last_64_kb_of_the_transcript_appear(self):
        filler = {"type": "system", "subtype": "turn_duration", "pad": "x" * (self.c.TAIL + 4096)}
        s = self.row([user(), assistant("m0", out=999, tools=("Grep",)), filler,
                      user("next"), assistant("m1", out=5, tools=("Bash",))])
        self.assertGreater(self.transcript.stat().st_size, self.c.TAIL)
        self.assertEqual(s.get("turns"), [5])
        self.assertEqual(s.get("recent", {}).get("trace"), ["Bash"])


class IncrementalTurnWindowTests(unittest.TestCase):
    def test_warm_transcript_window_matches_tail_oracle_through_file_changes(self):
        from codeteam2.deck import collect

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.jsonl"
            cache = collect.Cache()

            def check(step):
                records = collect.tail_records(path)
                expected_turns = collect.turn_stats(records)
                info = collect._transcript_info(str(path), cache)
                with self.subTest(step=step, field="trace"):
                    self.assertEqual(info["trace"], collect.recent_trace(records))
                with self.subTest(step=step, field="turns"):
                    self.assertEqual(info["turns"], expected_turns)
                with self.subTest(step=step, field="turns_left"):
                    self.assertEqual(collect.turns_left(info["turns"], 200000),
                                     collect.turns_left(expected_turns, 200000))
                return info

            def append(records):
                test_deck.append_text(path, "".join(json.dumps(record) + "\n" for record in records))

            def filler(n):
                return {"type": "system", "subtype": "turn_duration", "pad": "x" * n}
            write_jsonl(path, [user(), assistant("old", out=9, inp=1000, tools=("Old",)), filler(40000),
                               user(), assistant("shared", out=12, inp=10000, tools=("Read",))])
            self.assertEqual(check("initial")["trace"], ["Old", "Read"])

            append([assistant("shared", out=12, inp=10000, tools=("Edit",)),
                    user_blocks(tool_result()), assistant("next", out=3, inp=11000, tools=("Bash",))])
            info = check("extension with repeated message id")
            self.assertEqual(outputs(info["turns"]), [9, 15])
            self.assertEqual(info["trace"], ["Old", "Read", "Edit", "Bash"])

            append([BOUNDARY, user(), assistant("after1", out=4, inp=20000, tools=("Grep",)),
                    user(), assistant("after2", out=5, inp=30000, tools=("Write",))])
            info = check("compaction and two new turns")
            self.assertEqual(outputs(info["turns"]), [9, 15, {"compacted": True}, 4, 5])
            self.assertEqual(collect.turns_left(info["turns"], 200000), 17)

            append([filler(30000)])
            info = check("expiration")
            self.assertGreater(path.stat().st_size, collect.TAIL)
            self.assertEqual(info["trace"], ["Read", "Edit", "Bash", "Grep", "Write"])
            self.assertEqual(outputs(info["turns"]), [15, {"compacted": True}, 4, 5])

            before = path.stat().st_size
            write_jsonl(path, [user(), assistant("truncated", out=6, inp=40000, tools=("Read",)),
                               user(), assistant("more", out=7, inp=50000, tools=("Bash",))])
            self.assertLess(path.stat().st_size, before)
            self.assertEqual(check("truncation")["trace"], ["Read", "Bash"])

            st = path.stat()
            replacement = path.with_suffix(".replacement")
            replacement.write_text(path.read_text().replace('"Read"', '"Edit"'))
            os.utime(replacement, ns=(st.st_atime_ns, st.st_mtime_ns))
            self.assertEqual(replacement.stat().st_size, st.st_size)
            self.assertNotEqual(replacement.stat().st_ino, st.st_ino)
            replacement.replace(path)
            self.assertEqual(check("replacement inode")["trace"], ["Edit", "Bash"])

            before = path.stat().st_size
            append([filler(collect.TAIL + 1000), user(), assistant("big1", out=8, inp=60000, tools=("Grep",)),
                    user(), assistant("big2", out=9, inp=70000, tools=("Write",))])
            self.assertGreater(path.stat().st_size - before, collect.TAIL)
            info = check("append larger than TAIL")
            self.assertEqual(info["trace"], ["Grep", "Write"])
            self.assertEqual(outputs(info["turns"]), [8, 9])
            self.assertEqual(collect.turns_left(info["turns"], 200000), 13)


class TeamMessageTargetTests(unittest.TestCase):
    def setUp(self):
        from codeteam2.deck import collect
        from codeteam2.store import Store

        self.c = collect
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.folders = silent_lane_fixture(root, root / "wt")
        self.path = root / "team-tessa" / "team" / "v2" / "messages.db"
        store = Store(self.path)
        self.addCleanup(store.db.close)
        ids = test_deck.seed_messages(store)
        store.db.execute("UPDATE messages SET recipient=? WHERE id=?", ("all", ids["broadcast"]))
        self.expected = []
        for name in ("broadcast", "direct", "queued", "held", "old"):
            r = store.get(ids[name])
            self.expected.append({"id": r["id"], "ts": r["ts"], "sender": r["sender"], "kind": r["kind"],
                                  "recipient": r["recipient"], "target": r["target"],
                                  "text": " ".join(r["body"][:400].split())[:80]})

    def test_message_summary_last_carries_each_store_target_without_changing_other_fields(self):
        messages = self.c.read_messages(self.path, NOW)
        self.assertEqual([m["target"] for m in messages["recent"]], ["orc", "orc", "a", "b", "a"])
        self.assertEqual(messages["last"], self.expected)

    def test_collected_team_last_carries_the_target_even_for_a_broadcast(self):
        herdr = ReadOnlyHerdr(agents=[{"pane_id": "p-a", "name": "tessa-a", "agent_status": "working"}],
                              panes=[{"pane_id": "p-a", "label": "tessa-a"}])
        snap = self.c.collect(now=NOW, herdr=herdr, ps_text="", **self.folders)
        last = snap["teams"][0]["messages"]["last"]
        self.assertEqual(self.expected[0]["recipient"], "all")
        self.assertEqual(last, self.expected)


if __name__ == "__main__":
    unittest.main()
