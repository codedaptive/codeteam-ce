import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share/claude-hooks"))
import orc_git_refusal as module


@pytest.fixture
def calls(monkeypatch):
    calls = []
    def worktree(*args):
        calls.append(("worktree", *args))
        return "WORKTREE WHY"
    def from_file(*args):
        calls.append(("from_file", *args))
        return "FROM FILE WHY" if "--pathspec-from-file=list" in args[1] else None
    def pathspec(sub, a, gcwd, manifest, home):
        calls.append(("pathspec", sub, a))
        return f"PKG {a}" if a.startswith("packages/") else None
    monkeypatch.setattr(module, "orc_git_worktree", worktree)
    monkeypatch.setattr(module, "orc_judge_from_file", from_file)
    monkeypatch.setattr(module, "orc_judge_pathspec", pathspec)
    return calls


def refuse(sub, rest):
    return module.orc_git_refusal(sub, rest, "/cwd", ["/cwd"], "manifest", "home")


@pytest.mark.parametrize("sub", ["commit", "merge", "push"])
def test_other_subcommands_are_not_judged(calls, sub):
    assert refuse(sub, ["packages/widget"]) is None
    assert calls == []


@pytest.mark.parametrize("sub", ["restore", "checkout", "clean", "reset", "stash"])
def test_worktree_subcommands_give_orc_git_worktree_reason(calls, sub):
    assert refuse(sub, ["--hard"]) == "WORKTREE WHY"
    assert calls == [("worktree", sub, ["--hard"], "/cwd", ["/cwd"], "manifest", "home")]


@pytest.mark.parametrize("rest", [["packages/widget"], ["."], ["--pathspec-from-file=list"]])
def test_add_is_not_judged(calls, rest):
    assert refuse("add", rest) is None
    assert calls == []


@pytest.mark.parametrize("sub", ["rm", "mv"])
def test_first_package_pathspec_refuses(calls, sub):
    assert refuse(sub, ["docs/x.md", "packages/a", "packages/b"]) == "PKG packages/a"
    assert [c for c in calls if c[0] == "pathspec"] == [("pathspec", sub, "docs/x.md"), ("pathspec", sub, "packages/a")]


def test_dash_a_is_skipped(calls):
    assert refuse("rm", ["--", "-A", "docs/x.md"]) is None
    assert [c[2] for c in calls if c[0] == "pathspec"] == ["docs/x.md"]


def test_words_after_double_dash_are_the_pathspecs(calls):
    assert refuse("rm", ["docs/x.md", "--", "packages/widget"]) == "PKG packages/widget"
    assert [c[2] for c in calls if c[0] == "pathspec"] == ["packages/widget"]


def test_options_are_skipped(calls):
    assert refuse("rm", ["-f", "--cached", "docs/x.md"]) is None
    assert [c[2] for c in calls if c[0] == "pathspec"] == ["docs/x.md"]


def test_from_file_reason_wins_first(calls):
    assert refuse("rm", ["--pathspec-from-file=list", "packages/widget"]) == "FROM FILE WHY"
    assert [c[0] for c in calls] == ["from_file"]
