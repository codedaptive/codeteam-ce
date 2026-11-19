import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share/claude-hooks"))
import orc_judge_pathspec as module


@pytest.fixture
def calls(monkeypatch):
    calls = []
    def pathspec(*args):
        calls.append(("pathspec", *args))
        return None if args[0] == ":!x" else "/resolved"
    def refusal(*args):
        calls.append(("refusal", *args))
        return "WHY" if args[1] == "manifest" else None
    monkeypatch.setattr(module, "orc_pathspec", pathspec)
    monkeypatch.setattr(module, "orc_package_refusal", refusal)
    return calls


@pytest.mark.parametrize("arg,cwd", [("$HOME/x", "/cwd"), ("prefix/$X", "/cwd"), ("relative", None)])
def test_unknown_paths_pass_without_collaborators(calls, arg, cwd):
    assert module.orc_judge_pathspec("rm", arg, cwd, "manifest", "home") is None
    assert calls == []


def test_absolute_path_with_unknown_cwd_uses_root(calls):
    assert module.orc_judge_pathspec("rm", "/x", None, "manifest", "home") == "git rm on `/x`: WHY"
    assert calls == [("pathspec", "/x", "/"), ("refusal", "/resolved", "manifest", "home")]


def test_exclude_passes_without_package_check(calls):
    assert module.orc_judge_pathspec("rm", ":!x", "/cwd", "manifest", "home") is None
    assert calls == [("pathspec", ":!x", "/cwd")]


def test_refusal_names_original_argument(calls):
    assert module.orc_judge_pathspec("rm", "crates/x", "/cwd", "manifest", "home") == "git rm on `crates/x`: WHY"
    assert calls == [("pathspec", "crates/x", "/cwd"), ("refusal", "/resolved", "manifest", "home")]


def test_allowed_package_passes(calls):
    assert module.orc_judge_pathspec("restore", "docs", "/cwd", "allowed", "home") is None
    assert calls == [("pathspec", "docs", "/cwd"), ("refusal", "/resolved", "allowed", "home")]
