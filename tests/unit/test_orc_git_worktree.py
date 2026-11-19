import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share/claude-hooks"))
import orc_git_worktree as module


@pytest.fixture
def setup(monkeypatch):
    calls = []
    state = {"paths": ["a", "b", "c"], "bad": None, "rewrites": False}
    def stash(*args):
        calls.append(("stash", *args))
        return "git stash in `/top`: WHY"
    def paths(*args):
        calls.append(("paths", *args))
        return state["paths"]
    def path(*args):
        calls.append(("path", *args))
        return "git checkout on `b`: WHY" if args[1] == state["bad"] else None
    def from_file(*args):
        calls.append(("file", *args))
        return "git restore in `/top`: WHY"
    def rewrites(*args):
        calls.append(("rewrites", *args))
        return state["rewrites"]
    def top(*args):
        calls.append(("top", *args))
        return "git clean in `/top`: WHY"
    monkeypatch.setattr(module, "orc_git_stash", stash)
    monkeypatch.setattr(module, "orc_git_paths", paths)
    monkeypatch.setattr(module, "orc_judge_pathspec", path)
    monkeypatch.setattr(module, "orc_judge_from_file", from_file)
    monkeypatch.setattr(module, "orc_rewrites_worktree", rewrites)
    monkeypatch.setattr(module, "orc_judge_top", top)
    return calls, state


def test_stash_delegates_without_other_checks(setup):
    calls, _ = setup
    assert module.orc_git_worktree("stash", ["push"], "/cwd", ["where"], "manifest", "home") == "git stash in `/top`: WHY"
    assert calls == [("stash", ["push"], "/cwd", ["where"], "manifest", "home")]


@pytest.mark.parametrize("sub", ["restore", "checkout"])
def test_paths_checked_in_order_before_file(setup, sub):
    calls, state = setup
    state["paths"] = ["a", "b"]
    assert module.orc_git_worktree(sub, ["args"], "/cwd", ["where"], "manifest", "home") == "git restore in `/top`: WHY"
    assert calls == [("paths", sub, ["args"]), ("path", sub, "a", "/cwd", "manifest", "home"),
                     ("path", sub, "b", "/cwd", "manifest", "home"),
                     ("file", sub, ["args"], "/cwd", ["where"], "manifest", "home")]


def test_path_refusal_stops_before_file_and_later_paths(setup):
    calls, state = setup
    state["bad"] = "b"
    assert module.orc_git_worktree("checkout", ["args"], "/cwd", ["where"], "manifest", "home") == "git checkout on `b`: WHY"
    assert calls == [("paths", "checkout", ["args"]), ("path", "checkout", "a", "/cwd", "manifest", "home"),
                     ("path", "checkout", "b", "/cwd", "manifest", "home")]


@pytest.mark.parametrize("sub", ["clean", "reset"])
@pytest.mark.parametrize("rewrites", [True, False])
def test_clean_and_reset_only_judge_top_when_rewriting(setup, sub, rewrites):
    calls, state = setup
    state["rewrites"] = rewrites
    result = module.orc_git_worktree(sub, ["args"], "/cwd", ["where"], "manifest", "home")
    if rewrites:
        assert result == "git clean in `/top`: WHY"
        assert calls == [("rewrites", sub, ["args"]), ("top", sub, "/cwd", ["where"], "manifest", "home")]
    else:
        assert result is None
        assert calls == [("rewrites", sub, ["args"])]
