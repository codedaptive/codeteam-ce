import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_declared_seed import declared_seed


def test_declared_seed_passes():
    assert declared_seed({"kind": "function", "path": "A/own.rs"}, {"function"}, ["tests/"]) is True


def test_unlisted_kind_fails():
    assert declared_seed({"kind": "module", "path": "A/own.rs"}, {"function"}, ["tests/"]) is False


def test_whole_file_fails():
    assert declared_seed({"kind": "function", "path": "A/own.rs", "wholeFile": True}, {"function"}, ["tests/"]) is False


def test_test_mark_anywhere_in_path_fails():
    assert declared_seed({"kind": "function", "path": "A/tests/own.rs"}, {"function"}, ["tests/"]) is False
