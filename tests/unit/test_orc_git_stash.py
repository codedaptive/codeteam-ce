import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share/claude-hooks"))
import orc_git_stash as module


@pytest.fixture
def setup(monkeypatch):
    calls = []
    state = {"action": "", "paths": [], "from_file": False, "bad": None}
    def words(rest):
        calls.append(("words", rest))
        return state["action"], state["paths"]
    def path(*args):
        calls.append(("path", *args))
        return "git stash on `b`: WHY" if args[1] == state["bad"] else None
    def from_file(rest):
        calls.append(("file", rest))
        return state["from_file"]
    def top(*args):
        calls.append(("top", *args))
        return "git stash in `/top`: WHY"
    monkeypatch.setattr(module, "orc_stash_words", words)
    monkeypatch.setattr(module, "orc_judge_pathspec", path)
    monkeypatch.setattr(module, "orc_from_file", from_file)
    monkeypatch.setattr(module, "orc_judge_top", top)
    return calls, state


@pytest.mark.parametrize("action", ["list", "show", "drop", "clear", "create", "store"])
def test_read_only_actions_pass_without_judging(setup, action):
    calls, state = setup
    state.update(action=action, paths=["a"])
    assert module.orc_git_stash([action], "/cwd", ["where"], "manifest", "home") is None
    assert calls == [("words", [action])]


def test_push_stops_at_first_refusing_path(setup):
    calls, state = setup
    state.update(action="push", paths=["a", "b", "c"], bad="b")
    assert module.orc_git_stash(["push"], "/cwd", ["where"], "manifest", "home") == "git stash on `b`: WHY"
    assert calls == [("words", ["push"]), ("path", "stash", "a", "/cwd", "manifest", "home"),
                     ("path", "stash", "b", "/cwd", "manifest", "home")]


def test_push_with_paths_and_no_file_passes(setup):
    calls, state = setup
    state.update(action="push", paths=["a", "b"])
    assert module.orc_git_stash(["push", "a", "b"], "/cwd", ["where"], "manifest", "home") is None
    assert calls == [("words", ["push", "a", "b"]), ("path", "stash", "a", "/cwd", "manifest", "home"),
                     ("path", "stash", "b", "/cwd", "manifest", "home"), ("file", ["push", "a", "b"])]


@pytest.mark.parametrize("action", ["", "save", "pop", "apply", "branch"])
def test_bare_and_apply_actions_judge_top(setup, action):
    calls, state = setup
    state["action"] = action
    rest = [action] if action else []
    assert module.orc_git_stash(rest, "/cwd", ["where"], "manifest", "home") == "git stash in `/top`: WHY"
    assert calls == [("words", rest), ("top", "stash", "/cwd", ["where"], "manifest", "home")]


def test_push_with_file_judges_paths_then_top(setup):
    calls, state = setup
    state.update(action="push", paths=["a"], from_file=True)
    rest = ["push", "--pathspec-from-file=names", "a"]
    assert module.orc_git_stash(rest, "/cwd", ["where"], "manifest", "home") == "git stash in `/top`: WHY"
    assert calls == [("words", rest), ("path", "stash", "a", "/cwd", "manifest", "home"),
                     ("file", rest), ("top", "stash", "/cwd", ["where"], "manifest", "home")]
