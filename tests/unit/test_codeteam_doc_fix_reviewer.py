import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_doc_fix_reviewer import doc_fix_reviewer


def test_pending_reviewer_may_fix():
    row = {"wo": "docfix", "stage": 3, "state": "pending", "reviewers": {"Kong": "pending"}}
    assert doc_fix_reviewer(row, "Kong") is None


@pytest.mark.parametrize("session", [None, ""])
def test_no_session_is_refused_before_other_checks(session):
    assert doc_fix_reviewer(None, session) == "set CODETEAM_SESSION to your session name"


def test_no_review_row_is_refused():
    assert doc_fix_reviewer(None, "Kong") == "it has no pending Stage 3 review"


def test_non_stage_3_review_is_refused():
    row = {"wo": "docfix", "stage": 2, "state": "pending", "reviewers": {"Kong": "pending"}}
    assert doc_fix_reviewer(row, "Kong") == "docfix has no pending Stage 3 review"


def test_review_not_pending_is_refused():
    row = {"wo": "docfix", "stage": 3, "state": "pass", "reviewers": {"Kong": "pending"}}
    assert doc_fix_reviewer(row, "Kong") == "docfix has no pending Stage 3 review"


def test_another_session_is_refused():
    row = {"wo": "docfix", "stage": 3, "state": "pending", "reviewers": {"Kong": "pending"}}
    assert doc_fix_reviewer(row, "Other") == "Other is not a pending Stage 3 reviewer of docfix"


@pytest.mark.parametrize("verdict", ["pass", "findings"])
def test_reviewer_who_already_responded_is_refused(verdict):
    row = {"wo": "docfix", "stage": 3, "state": "pending", "reviewers": {"Kong": verdict}}
    assert doc_fix_reviewer(row, "Kong") == "Kong is not a pending Stage 3 reviewer of docfix"
