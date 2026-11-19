"""share/codeteam_carried_check.py (Orc-Codegraph #4653, D559): Stage 2 refuses a landing set that carries another open
work order's unlanded commits, unless that work order is in the set. Unit tests (rule 11): the records and git's
commit lists are fakes; nothing touches a repo."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
import codeteam_carried_order
from codeteam_carried_check import carried_check

COMMITS = {"/t/comment": ["c3", "c2", "c1"], "/t/host": ["c2", "c1"], "/t/other": ["c9"]}
# seed-schemaless-comment was cut after host and moved onto host's tip.
OPEN = [(Path("host.json"), {"wo": "host", "tree": "/t/host", "cut": "2026-11-17T09:00:00-06:00"}),
        (Path("other.json"), {"wo": "other", "tree": "/t/other", "cut": "2026-11-17T09:30:00-06:00"}),
        (Path("comment.json"), {"wo": "seed-schemaless-comment", "tree": "/t/comment",
                                "cut": "2026-11-17T10:00:00-06:00"})]


def refusal(names, queued=(), commits=COMMITS, open_records=OPEN):
    """The refusal text for landing these work orders as one set, or None when the set is let through."""
    records = [rec for _, rec in open_records if rec["wo"] in names]
    with patch.object(codeteam_carried_order, "unlanded_commits", lambda tree, landing: commits.get(tree, [])):
        return carried_check(SimpleNamespace(landing="landing"), records, lambda team: open_records,
                             lambda team, wo: wo in queued)


def test_a_work_order_carrying_an_open_ones_commits_is_refused_alone():
    text = refusal(["seed-schemaless-comment"])
    assert "host (c2)" in text
    assert "land seed-schemaless-comment --with host" in text
    assert "other (" not in text


def test_landing_it_with_the_carried_work_order_is_let_through():
    assert refusal(["seed-schemaless-comment", "host"]) is None


def test_a_carried_work_order_already_queued_is_waited_for():
    text = refusal(["seed-schemaless-comment"], queued=("host",))
    assert "host is already queued" in text
    assert "--with" not in text


def test_a_work_order_of_its_own_commits_only_is_let_through():
    assert refusal(["host"]) is None
    assert refusal(["other"]) is None


def test_after_host_moves_on_it_lands_alone_and_the_later_cut_one_is_still_refused():
    moved = {**COMMITS, "/t/host": ["c4", "c2", "c1"]}      # host fixed its Stage 3 finding forward
    assert refusal(["host"], commits=moved) is None
    assert "host (c2)" in refusal(["seed-schemaless-comment"], commits=moved)


def test_a_stand_in_record_without_a_cut_time_counts_as_cut_first():
    stand_in = (Path("lost.json"), {"wo": "lost", "tree": "/t/lost", "unregistered": True})
    commits = {**COMMITS, "/t/lost": ["c8", "c2", "c1"], "/t/host": ["c4", "c2", "c1"]}
    assert "lost (c2)" in refusal(["host"], commits=commits, open_records=[*OPEN, stand_in])
