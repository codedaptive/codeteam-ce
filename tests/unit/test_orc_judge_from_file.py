import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share/claude-hooks"))
import orc_judge_from_file as module


@pytest.mark.parametrize("from_file,index_only,expected,calls_expected", [
    (False, False, None, [("file", ["args"])]),
    (True, True, None, [("file", ["args"]), ("index", "restore", ["args"])]),
    (True, False, "git restore in `/top`: WHY", [("file", ["args"]), ("index", "restore", ["args"]),
                                                   ("top", "restore", "/cwd", ["where"], "manifest", "home")]),
])
def test_from_file_judges_top_only_for_worktree(monkeypatch, from_file, index_only, expected, calls_expected):
    calls = []
    def file_check(*args):
        calls.append(("file", *args))
        return from_file
    def index_check(*args):
        calls.append(("index", *args))
        return index_only
    def top(*args):
        calls.append(("top", *args))
        return "git restore in `/top`: WHY"
    monkeypatch.setattr(module, "orc_from_file", file_check)
    monkeypatch.setattr(module, "orc_index_only", index_check)
    monkeypatch.setattr(module, "orc_judge_top", top)
    assert module.orc_judge_from_file("restore", ["args"], "/cwd", ["where"], "manifest", "home") == expected
    assert calls == calls_expected
