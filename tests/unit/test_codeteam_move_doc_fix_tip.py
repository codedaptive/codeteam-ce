import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_move_doc_fix_tip import move_doc_fix_tip


def test_lone_entry_moves_tip_and_keeps_review_and_stage2_metadata():
    rec = {"wo": "one", "tip": "old", "files": ["a.md"],
           "stage2": [{"result": "pass"}], "zones": ["z"], "reach": ["r"],
           "set": ["one"], "no_build": True}
    entry = {"wo": "one", "tip": "old", "integration": "owed",
             "files": ["a.md"], "queued": "first", "zones": ["z"]}
    row = {"wo": "one", "tip": "old", "seen": ["base"],
           "reviewers": {"Kong": "pending"}, "requested": "once", "commits": ["old"]}
    partners = []
    assert move_doc_fix_tip(rec, entry, row, partners, "old", "new", ["a.md", "b.md", "b.md"]) is None
    assert rec == {"wo": "one", "tip": "new", "files": ["a.md", "b.md"],
                   "stage2": [{"result": "pass"}], "zones": ["z"], "reach": ["r"],
                   "set": ["one"], "no_build": True, "doc_fixes": ["new"]}
    assert entry == {"wo": "one", "tip": "new", "integration": "owed",
                     "files": ["a.md"], "queued": "first", "zones": ["z"]}
    assert row == {"wo": "one", "tip": "new", "seen": ["base"],
                   "reviewers": {"Kong": "pending"}, "requested": "once", "commits": ["old"]}
    assert partners == []


def test_set_nonfirst_member_moves_only_its_tips_and_partner_links():
    rec = {"wo": "two", "tip": "old", "files": ["a.md"], "doc_fixes": ["earlier"],
           "stage2": [{"result": "pass"}], "zones": ["z"], "reach": ["r"],
           "set": ["one", "two"], "no_build": False}
    entry = {"wo": "one", "tip": "first", "tips": [["one", "first"], ["two", "old"]],
             "integration": "owed", "files": ["a.md"], "queued": "first", "zones": ["z"]}
    row = {"wo": "two", "tip": "old", "seen": ["base"],
           "reviewers": {"Kong": "pending"}, "requested": "once", "commits": ["old"],
           "with": [{"wo": "one", "tip": "first"}]}
    partners = [{"wo": "one", "tip": "first", "with": [{"wo": "two", "tip": "old"},
                                                          {"wo": "three", "tip": "other"}]},
                {"wo": "three", "tip": "other", "with": [{"wo": "one", "tip": "first"}]}]
    assert move_doc_fix_tip(rec, entry, row, partners, "old", "new", ["b.md"]) is None
    assert rec == {"wo": "two", "tip": "new", "files": ["a.md", "b.md"],
                   "doc_fixes": ["earlier", "new"], "stage2": [{"result": "pass"}],
                   "zones": ["z"], "reach": ["r"], "set": ["one", "two"], "no_build": False}
    assert entry == {"wo": "one", "tip": "first", "tips": [["one", "first"], ["two", "new"]],
                     "integration": "owed", "files": ["a.md"], "queued": "first", "zones": ["z"]}
    assert row == {"wo": "two", "tip": "new", "seen": ["base"],
                   "reviewers": {"Kong": "pending"}, "requested": "once", "commits": ["old"],
                   "with": [{"wo": "one", "tip": "first"}]}
    assert partners == [{"wo": "one", "tip": "first", "with": [{"wo": "two", "tip": "new"},
                                                                  {"wo": "three", "tip": "other"}]},
                        {"wo": "three", "tip": "other", "with": [{"wo": "one", "tip": "first"}]}]


def test_set_first_member_moves_entry_tip_as_well_as_member():
    rec = {"wo": "one", "tip": "old", "files": [], "stage2": ["pass"],
           "zones": ["z"], "reach": ["r"], "set": ["one", "two"], "no_build": True}
    entry = {"wo": "one", "tip": "old", "tips": [["one", "old"], ["two", "second"]],
             "integration": "owed", "files": [], "queued": "first"}
    row = {"wo": "one", "tip": "old", "seen": [], "reviewers": {"Kong": "pending"},
           "requested": "once", "commits": ["old"]}
    partners = [{"wo": "two", "tip": "second", "with": [{"wo": "one", "tip": "old"}]}]
    assert move_doc_fix_tip(rec, entry, row, partners, "old", "new", ["new.md"]) is None
    assert rec == {"wo": "one", "tip": "new", "files": ["new.md"], "stage2": ["pass"],
                   "zones": ["z"], "reach": ["r"], "set": ["one", "two"],
                   "no_build": True, "doc_fixes": ["new"]}
    assert entry == {"wo": "one", "tip": "new", "tips": [["one", "new"], ["two", "second"]],
                     "integration": "owed", "files": [], "queued": "first"}
    assert row == {"wo": "one", "tip": "new", "seen": [], "reviewers": {"Kong": "pending"},
                   "requested": "once", "commits": ["old"]}
    assert partners == [{"wo": "two", "tip": "second", "with": [{"wo": "one", "tip": "new"}]}]


@pytest.mark.parametrize("mismatch", ["record", "row", "lone_entry", "set_old", "set_wo"])
def test_mismatch_raises_without_mutating_any_input(mismatch):
    rec = {"wo": "one", "tip": "old", "files": ["a.md"], "doc_fixes": ["previous"]}
    entry = {"wo": "one", "tip": "old"}
    row = {"wo": "one", "tip": "old", "reviewers": {"Kong": "pending"}}
    partners = [{"wo": "two", "tip": "second", "with": [{"wo": "one", "tip": "old"}]}]
    if mismatch == "record":
        rec["tip"] = "wrong"
    elif mismatch == "row":
        row["tip"] = "wrong"
    elif mismatch == "lone_entry":
        entry["tip"] = "wrong"
    elif mismatch == "set_old":
        entry["tips"] = [["one", "wrong"], ["two", "old"]]
    else:
        entry["tips"] = [["other", "old"]]
    before = deepcopy((rec, entry, row, partners))
    with pytest.raises(ValueError):
        move_doc_fix_tip(rec, entry, row, partners, "old", "new", ["b.md"])
    assert (rec, entry, row, partners) == before
