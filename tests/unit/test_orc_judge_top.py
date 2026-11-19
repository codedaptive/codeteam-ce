import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share/claude-hooks"))
import orc_judge_top as module


@pytest.fixture
def calls(monkeypatch):
    calls = []
    def top(where):
        calls.append(("top", where))
        return {"first": "/one", "second": "/top", "third": "/three"}[where]
    def refusal(*args):
        calls.append(("refusal", *args))
        return "WHY" if args[0] in ("/top", "/three") else None
    monkeypatch.setattr(module, "git_top", top)
    monkeypatch.setattr(module, "orc_package_refusal", refusal)
    return calls


def test_unknown_cwd_passes_without_queries(calls):
    assert module.orc_judge_top("stash", None, ["second"], "manifest", "home") is None
    assert calls == []


def test_first_refusing_top_wins_in_where_order(calls):
    assert module.orc_judge_top("stash", "/cwd", ["first", "second", "third"], "manifest", "home") == "git stash in `/top`: WHY"
    assert calls == [("top", "first"), ("refusal", "/one", "manifest", "home"),
                     ("top", "second"), ("refusal", "/top", "manifest", "home")]


def test_all_allowed_tops_pass(calls):
    assert module.orc_judge_top("clean", "/cwd", ["first"], "manifest", "home") is None
    assert calls == [("top", "first"), ("refusal", "/one", "manifest", "home")]
