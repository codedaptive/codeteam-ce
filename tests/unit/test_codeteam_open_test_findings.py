import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_open_test_findings import open_test_findings


def test_keeps_open_test_findings_not_filed_by_validation_in_order():
    findings = [{"id": "a#1", "state": "open", "test": "tests A (a)", "by": "recheck"},
                {"id": "a#2", "state": "closed", "test": "tests A (a)", "by": "recheck"},
                {"id": "a#3", "state": "open", "by": "kong"},
                {"id": "a#4", "state": "open", "test": "tests B (b)", "by": "validation"},
                {"id": "a#5", "state": "open", "test": "tests C (c)"}]
    assert [fix["id"] for fix in open_test_findings(iter(findings))] == ["a#1", "a#5"]


def test_nothing_open():
    assert open_test_findings([]) == []
