import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_batch_tree import batch_tree


def test_empty_batch_keeps_base_without_calls():
    calls = []
    assert batch_tree("base", [], lambda *a: calls.append(a), lambda *a: calls.append(a)) == ("base", [])
    assert calls == []


def test_entries_and_members_chain_in_order():
    calls = []
    def merge(cur, wo, tip):
        calls.append((cur, wo, tip))
        return {"a": "m1", "b": "m2", "c": "m3"}[wo], []
    assert batch_tree("base", [("first", [("a", "ta"), ("b", "tb")]),
                               ("second", [("c", "tc")])], merge,
                      lambda *args: calls.append(("conflict", *args))) == ("m3", ["first", "second"])
    assert calls == [("base", "a", "ta"), ("m1", "b", "tb"), ("m2", "c", "tc")]


def test_conflict_rolls_back_whole_entry_and_keeps_later_entries():
    calls = []
    def merge(cur, wo, tip):
        calls.append(("merge", cur, wo, tip))
        return (None, ["bad.py"]) if wo == "b" else (f"commit-{wo}", [])
    assert batch_tree("base", [("first", [("a", "ta"), ("b", "tb"), ("never", "tn")]),
                               ("second", [("c", "tc")])], merge,
                      lambda *args: calls.append(("conflict", *args))) == ("commit-c", ["second"])
    assert calls == [("merge", "base", "a", "ta"), ("merge", "commit-a", "b", "tb"),
                     ("conflict", "first", ["bad.py"], "b"), ("merge", "base", "c", "tc")]
