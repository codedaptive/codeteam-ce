import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_trusted_callers import trusted_callers


def test_complete_answer_keeps_files():
    assert trusted_callers({"B": ["B/caller.rs"]}, {}) == {"B": ["B/caller.rs"]}


def test_incomplete_answer_is_unknown():
    note = {"interface_error": "codegraph callers own: incomplete answer, calling zones may be missing"}
    assert trusted_callers({"B": ["B/caller.rs"]}, note) is None


def test_failed_query_is_unknown():
    assert trusted_callers({}, {"interface_error": "codegraph callers own: TimeoutExpired"}) is None
