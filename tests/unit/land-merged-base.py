#!/usr/bin/env -S python3 -u
"""Unit contract for constructing a merged base from independent bases."""
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "share"))
from codeteam_merged_base import merged_base


class FakeGit:
    def __init__(self, refs, independent, trees=None, commits=None):
        self.refs = refs
        self.independent = independent
        self.trees = list(trees if trees is not None else [(0, "tree1\n"), (0, "tree2\n")])
        self.commits = list(commits if commits is not None else [(0, "commit1\n"), (0, "commit2\n")])
        self.calls = []

    def __call__(self, *args, env=None):
        self.calls.append((args, env))
        if args[:2] == ("merge-base", "--all"):
            result = self.refs[args[3]]
        elif args[:2] == ("merge-base", "--independent"):
            result = self.independent
        elif args[:2] == ("merge-tree", "--write-tree"):
            result = self.trees.pop(0)
        elif args[0] == "commit-tree":
            result = self.commits.pop(0)
        else:
            raise AssertionError(args)
        if isinstance(result, OSError):
            raise result
        return SimpleNamespace(returncode=result[0], stdout=result[1])


def fake(independent="a\nb\n", **kwargs):
    return FakeGit({"r1": (0, "a\n"), "r2": (0, "b\n")}, (0, independent), **kwargs)


def test_one_independent_base_returns_none_without_merging():
    git = fake("a\n")
    assert merged_base(git, "tip", ["r1", "r2"]) is None
    assert all(args[0] not in ("merge-tree", "commit-tree") for args, _ in git.calls)


def test_two_bases_use_both_parents_and_fixed_identity():
    git = fake()
    assert merged_base(git, "tip", ["r1", "r2"]) == "commit1"
    assert ("merge-base", "--independent", "a", "b") in [args for args, _ in git.calls]
    assert ("merge-tree", "--write-tree", "a", "b") in [args for args, _ in git.calls]
    args, env = next(call for call in git.calls if call[0][0] == "commit-tree")
    assert args[1:6] == ("tree1", "-p", "a", "-p", "b"), args
    assert "-m" in args
    keys = ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_AUTHOR_DATE", "GIT_COMMITTER_NAME",
            "GIT_COMMITTER_EMAIL", "GIT_COMMITTER_DATE")
    assert env is not None and all(env.get(k) for k in keys), env
    again = fake()
    assert merged_base(again, "tip", ["r1", "r2"]) == "commit1"
    other_env = next(e for a, e in again.calls if a[0] == "commit-tree")
    assert {k: env[k] for k in keys} == {k: other_env[k] for k in keys}


def test_three_bases_are_folded_in_order():
    git = FakeGit({"r1": (0, "a\nb\n"), "r2": (0, "c\n")}, (0, "a\nb\nc\n"))
    assert merged_base(git, "tip", ["r1", "r2"]) == "commit2"
    assert [args for args, _ in git.calls if args[0] == "merge-tree"] == [
        ("merge-tree", "--write-tree", "a", "b"), ("merge-tree", "--write-tree", "commit1", "c")]
    parents = [args[1:6] for args, _ in git.calls if args[0] == "commit-tree"]
    assert parents == [("tree1", "-p", "a", "-p", "b"), ("tree2", "-p", "commit1", "-p", "c")]


def test_merge_tree_failure_returns_none():
    git = fake(trees=[(1, "conflict\n")])
    assert merged_base(git, "tip", ["r1", "r2"]) is None
    assert not any(args[0] == "commit-tree" for args, _ in git.calls)


def test_commit_tree_failure_returns_none():
    assert merged_base(fake(commits=[(1, "")]), "tip", ["r1", "r2"]) is None


def test_oserror_returns_none():
    git = FakeGit({"r1": OSError("git unavailable")}, (0, ""))
    assert merged_base(git, "tip", ["r1"]) is None


def test_failed_ref_is_skipped():
    git = FakeGit({"bad": (1, "ignored\n"), "good": (0, "a\nb\n"), "empty": (0, "")}, (0, "a\nb\n"))
    assert merged_base(git, "tip", ["bad", "good", "empty"]) == "commit1"
    assert ("merge-base", "--independent", "a", "b") in [args for args, _ in git.calls]


def test_empty_or_failed_intermediate_output_returns_none():
    for git in (fake(trees=[(0, "")]), fake(commits=[(0, "")]),
                FakeGit({"r1": (0, "a\nb\n")}, (1, "a\nb\n"))):
        assert merged_base(git, "tip", ["r1"]) is None


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn()
                print(f"  PASS {name}")
            except Exception as ex:
                failed += 1
                print(f"  FAIL {name}: {type(ex).__name__}: {ex}")
    print("all passed" if not failed else f"{failed} failed")
    raise SystemExit(1 if failed else 0)
