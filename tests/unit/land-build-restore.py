#!/usr/bin/env -S python3 -u
"""Stage 2 puts back committed files its build changed, and a merge that fails without a conflict says why
(2026-11-12: a lane's unit build rewrote a stale Cargo.lock in the work order tree, and land's
`git merge integration` then failed with an empty 'conflicts in:' list)."""
import contextlib
import importlib.machinery
import importlib.util
import io
import os
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ["CODETEAM_QUEUE_DIR"] = str(Path(tempfile.mkdtemp(prefix="land-queue-")) / "queue")

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_build_restore", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)


def sh(tree, *args):
    subprocess.run(["git", *args], cwd=tree, check=True, capture_output=True, text=True)


def repo(d):
    """A work order tree on branch wo with Cargo.lock committed, and branch integration one commit ahead that
    changes Cargo.lock and adds a file."""
    tree = Path(d) / "tree"
    tree.mkdir()
    sh(tree, "init", "-q", "-b", "wo")
    sh(tree, "config", "user.email", "t@example.com")
    sh(tree, "config", "user.name", "t")
    (tree / "Cargo.lock").write_text("version = 4\n")
    (tree / "src.rs").write_text("fn main() {}\n")
    sh(tree, "add", ".")
    sh(tree, "commit", "-q", "-m", "base")
    sh(tree, "branch", "integration")
    sh(tree, "checkout", "-q", "integration")
    (tree / "Cargo.lock").write_text("version = 4\n[[package]]\nname = \"vcs\"\n")
    sh(tree, "commit", "-q", "-am", "integration moves the lock")
    sh(tree, "checkout", "-q", "wo")
    return tree


def team():
    return SimpleNamespace(integration="integration", save_wo=Mock())


def test_a_build_that_rewrites_a_committed_file_leaves_the_tree_as_committed():
    with tempfile.TemporaryDirectory() as d:
        tree = repo(d)
        rec = {"wo": "agent-tools", "tree": str(tree)}
        printed = io.StringIO()
        with patch.object(cl, "team_env", return_value=dict(os.environ)), contextlib.redirect_stdout(printed):
            ok = cl.stage2_steps(team(), rec, [("tests tools (crates/tool-support)",
                                                "printf 'name = \"stale\"\\n' >> Cargo.lock")], "unit")
        assert ok
        assert subprocess.run(["git", "status", "--porcelain"], cwd=tree, capture_output=True, text=True).stdout == ""
        assert "the build changed Cargo.lock, which the commit holds; restored as committed" in printed.getvalue()
        assert rec["stage2"][0]["result"] == "pass"


def test_a_file_changed_before_the_batch_is_left_alone():
    with tempfile.TemporaryDirectory() as d:
        tree = repo(d)
        (tree / "src.rs").write_text("fn main() { mine() }\n")
        rec = {"wo": "agent-tools", "tree": str(tree)}
        with patch.object(cl, "team_env", return_value=dict(os.environ)), contextlib.redirect_stdout(io.StringIO()):
            cl.stage2_steps(team(), rec, [("tests", "printf x >> Cargo.lock")], "unit")
        assert (tree / "src.rs").read_text() == "fn main() { mine() }\n"
        assert (tree / "Cargo.lock").read_text() == "version = 4\n"


def test_a_merge_git_refuses_names_git_s_reason_not_an_empty_conflict_list():
    with tempfile.TemporaryDirectory() as d:
        tree = repo(d)
        (tree / "Cargo.lock").write_text("version = 4\nstale\n")      # what the build left before this fix
        printed = io.StringIO()
        base = subprocess.run(["git", "rev-parse", "integration"], cwd=tree, capture_output=True, text=True).stdout.strip()
        with contextlib.redirect_stdout(printed):
            try:
                cl.merge_checked_base(team(), {"wo": "agent-tools", "tree": str(tree)}, base, only_docs=True, test=False)
            except SystemExit as ex:
                assert ex.code == cl.CONFLICT
            else:
                raise AssertionError("the merge should have failed")
        text = printed.getvalue()
        assert "failed with no conflicted file; git said:" in text, text
        assert "Cargo.lock" in text and "overwritten by merge" in text, text
        assert "conflicts in:\n\n" not in text


def test_a_real_conflict_still_lists_its_files():
    with tempfile.TemporaryDirectory() as d:
        tree = repo(d)
        (tree / "Cargo.lock").write_text("version = 4\n[[package]]\nname = \"other\"\n")
        sh(tree, "commit", "-q", "-am", "the work order moves the lock too")
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            try:
                cl.merge_checked_base(team(), {"wo": "agent-tools", "tree": str(tree)}, "integration", only_docs=True,
                                      test=False)
            except SystemExit as ex:
                assert ex.code == cl.CONFLICT
        assert "merging integration conflicts in:\nCargo.lock\n" in printed.getvalue(), printed.getvalue()


if __name__ == "__main__":
    test_a_build_that_rewrites_a_committed_file_leaves_the_tree_as_committed()
    test_a_file_changed_before_the_batch_is_left_alone()
    test_a_merge_git_refuses_names_git_s_reason_not_an_empty_conflict_list()
    test_a_real_conflict_still_lists_its_files()
    print("all passed")
