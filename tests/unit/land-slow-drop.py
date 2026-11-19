#!/usr/bin/env -S python3 -u
"""Drop_slow marks an open slow-tests follow-up dropped, with its reason, time and dropper,
and answers None for an id that is not open. Pure: a list in, a list out."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "share"))
from codeteam_slow_drop import drop_slow  # noqa: E402


def entry(ident, state="open", zone="cli"):
    return {"id": ident, "zone": zone, "state": state, "closed": None, "closed_by": None}


def test_drops_the_open_entry_and_leaves_the_rest():
    items = [entry("slow#1"), entry("slow#2", zone="gadget")]
    assert drop_slow(items, "slow#1", "measured lock waits", "Orc-Widgets", "NOW") == [
        {"id": "slow#1", "zone": "cli", "state": "dropped", "closed": "NOW", "closed_by": None,
         "reason": "measured lock waits", "dropped_by": "Orc-Widgets"},
        entry("slow#2", zone="gadget")]


def test_unknown_id_is_none():
    assert drop_slow([entry("slow#1")], "slow#9", "r", "S", "NOW") is None


def test_closed_or_dropped_id_is_none():
    for state in ("closed", "dropped"):
        assert drop_slow([entry("slow#1", state=state)], "slow#1", "r", "S", "NOW") is None, state


def test_empty_list_is_none():
    assert drop_slow([], "slow#1", "r", "S", "NOW") is None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("all passed")
