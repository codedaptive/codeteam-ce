import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_callees_incomplete_clause import callees_incomplete_clause


@pytest.mark.parametrize("result", [{}, {"callees_incomplete": []}])
def test_missing_or_empty_callees_incomplete_has_no_clause(result):
    assert callees_incomplete_clause(result) == ""


def test_one_incomplete_test_has_exact_clause():
    assert callees_incomplete_clause({"callees_incomplete": ["test_a"]}) == (
        "CodeGraph's callees were incomplete for test_a; matched on the stack alone"
    )


def test_two_incomplete_tests_have_exact_clause():
    assert callees_incomplete_clause({"callees_incomplete": ["test_a", "test_b"]}) == (
        "CodeGraph's callees were incomplete for test_a, test_b; matched on the stack alone"
    )
