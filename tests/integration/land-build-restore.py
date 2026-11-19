#!/usr/bin/env -S python3 -u
"""Stage 2 puts back committed files its build changed, and a merge that fails without a conflict says why
(tools' unit build rewrote a stale Cargo.lock in the work order tree, and land's
`git merge integration` then failed with an empty 'conflicts in:' list). A lock the work order itself made stale, by
changing the manifest that feeds it, fails Stage 2 (2026-11-13). These are integration
tests: each runs real git in a temp repository, and Stage 2's steps as real shell commands. The unit
test of lock_inputs is in tests/unit/land-build-restore.py."""
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
    return SimpleNamespace(integration="integration", landing="landing", save_wo=Mock())


def commit(tree, path, text):
    (tree / path).parent.mkdir(parents=True, exist_ok=True)
    (tree / path).write_text(text)
    sh(tree, "add", path)
    sh(tree, "commit", "-q", "-m", f"work order changes {path}")


def stage2(tree, step):
    rec = {"wo": "agent-tools", "tree": str(tree)}
    printed = io.StringIO()
    with patch.object(cl, "team_env", return_value=dict(os.environ)), contextlib.redirect_stdout(printed):
        ok = cl.stage2_steps(team(), rec, [("tests tools", step)], "unit")
    return ok, rec, printed.getvalue()


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



def test_a_lock_the_work_order_made_stale_fails_stage_2_and_names_it():
    # widgets a crate joined the workspace with no lock entry, and the build regenerated Cargo.lock
    with tempfile.TemporaryDirectory() as d:
        tree = repo(d)
        commit(tree, "crates/blast/Cargo.toml", "[package]\nname = \"blast\"\n")
        ok, rec, text = stage2(tree, "printf 'name = \"blast\"\\n' >> Cargo.lock")
        assert not ok
        assert "FAIL agent-tools: its build rewrote Cargo.lock, which this work order made stale" in text, text
        assert "(Cargo.toml)" in text, text
        assert rec["stage2"][-1] == {"step": "committed lock files current", "result": "fail", "seconds": 0.0, "group": "unit"}
        assert subprocess.run(["git", "status", "--porcelain"], cwd=tree, capture_output=True, text=True).stdout == ""


def test_a_lock_already_stale_without_a_manifest_change_stays_a_notice():
    with tempfile.TemporaryDirectory() as d:
        tree = repo(d)
        commit(tree, "src.rs", "fn main() { tools() }\n")
        ok, rec, text = stage2(tree, "printf 'stale\\n' >> Cargo.lock")
        assert ok
        assert "restored as committed" in text and "FAIL" not in text, text


def test_a_manifest_change_the_lock_does_not_record_leaves_an_already_stale_lock_a_notice():
    # The lock was stale on integration and the work order changed only a description
    with tempfile.TemporaryDirectory() as d:
        tree = repo(d)
        commit(tree, "Cargo.toml", "[package]\nname = \"tools\"\nversion = \"0.1.0\"\n")
        sh(tree, "branch", "-f", "integration")
        commit(tree, "Cargo.toml", "[package]\nname = \"tools\"\nversion = \"0.1.0\"\ndescription = \"the tools\"\n")
        ok, rec, text = stage2(tree, "printf 'stale\\n' >> Cargo.lock")
        assert ok, text
        assert "restored as committed" in text and "FAIL" not in text, text


def test_a_dependency_change_still_fails_when_the_lock_was_already_stale():
    with tempfile.TemporaryDirectory() as d:
        tree = repo(d)
        commit(tree, "Cargo.toml", "[package]\nname = \"tools\"\n")
        sh(tree, "branch", "-f", "integration")
        commit(tree, "Cargo.toml", "[package]\nname = \"tools\"\ndescription = \"x\"\n[dependencies]\nserde = \"1\"\n")
        ok, _, text = stage2(tree, "printf 'serde\\n' >> Cargo.lock")
        assert not ok
        assert "which this work order made stale" in text, text


def test_a_manifest_outside_the_lock_s_folder_does_not_feed_it():
    with tempfile.TemporaryDirectory() as d:
        tree = repo(d)
        commit(tree, "Packages/A/Package.resolved", "{}\n")
        commit(tree, "Packages/B/Package.swift", "// B\n")
        ok, _, text = stage2(tree, "printf x >> Packages/A/Package.resolved")
        assert ok, text


if __name__ == "__main__":
    test_a_build_that_rewrites_a_committed_file_leaves_the_tree_as_committed()
    test_a_file_changed_before_the_batch_is_left_alone()
    test_a_merge_git_refuses_names_git_s_reason_not_an_empty_conflict_list()
    test_a_real_conflict_still_lists_its_files()
    test_a_lock_the_work_order_made_stale_fails_stage_2_and_names_it()
    test_a_lock_already_stale_without_a_manifest_change_stays_a_notice()
    test_a_manifest_change_the_lock_does_not_record_leaves_an_already_stale_lock_a_notice()
    test_a_dependency_change_still_fails_when_the_lock_was_already_stale()
    test_a_manifest_outside_the_lock_s_folder_does_not_feed_it()
    print("all passed")
