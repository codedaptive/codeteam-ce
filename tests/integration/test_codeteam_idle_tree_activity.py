import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_idle_tree_activity import idle_tree_activity


class FakeGit:
    """codeteam-land's git(tree, *args, check=False), answering `log` and `status` from canned results."""

    def __init__(self, log, status=""):
        self.log, self.status, self.calls = log, status, []

    def __call__(self, tree, *args, check=True):
        self.calls.append(args[0])
        return self.log if args[0] == "log" else SimpleNamespace(returncode=0, stdout=self.status, stderr="")


def committed(at):
    return SimpleNamespace(returncode=0, stdout=f"{at}\n", stderr="")


def test_landed_tree_with_git_is_active_at_zero_and_runs_no_git(tmp_path):
    (tmp_path / ".git").write_text("gitdir: elsewhere\n")
    git = FakeGit(committed(1000))
    assert idle_tree_activity(tmp_path, True, 600, 10_000, git) == ("landed_cleaned", 0.0, None)
    assert git.calls == []


def test_landed_tree_without_git_is_skipped_without_error(tmp_path):
    git = FakeGit(committed(1000))
    assert idle_tree_activity(tmp_path, True, 600, 10_000, git) == ("landed_cleaned", None, None)
    assert git.calls == []


def test_open_tree_where_log_fails_reports_the_error(tmp_path):
    git = FakeGit(SimpleNamespace(returncode=128, stdout="", stderr="fatal: not a git repository\n"))
    assert idle_tree_activity(tmp_path, False, 600, 10_000, git) == ("cleaned", None, "fatal: not a git repository")
    assert git.calls == ["log"]


def test_open_tree_with_a_commit_inside_the_limit_runs_no_status(tmp_path):
    git = FakeGit(committed(9500), status=" M x\n")
    assert idle_tree_activity(tmp_path, False, 600, 10_000, git) == ("cleaned", 9500.0, None)
    assert git.calls == ["log"]


def test_open_tree_past_the_limit_takes_a_newer_edit(tmp_path):
    (tmp_path / "x").write_text("edit")
    os.utime(tmp_path / "x", (5000, 5000))
    git = FakeGit(committed(1000), status=" M x\n")
    assert idle_tree_activity(tmp_path, False, 600, 10_000, git) == ("cleaned", 5000.0, None)
    assert git.calls == ["log", "status"]


def test_open_tree_keeps_its_commit_when_the_edit_is_older(tmp_path):
    (tmp_path / "x").write_text("edit")
    os.utime(tmp_path / "x", (500, 500))
    git = FakeGit(committed(1000), status="?? x\n")
    assert idle_tree_activity(tmp_path, False, 600, 10_000, git) == ("cleaned", 1000.0, None)


def test_a_rename_is_judged_by_its_new_name(tmp_path):
    (tmp_path / "new").write_text("moved")
    os.utime(tmp_path / "new", (7000, 7000))
    git = FakeGit(committed(1000), status="R  old -> new\n")
    assert idle_tree_activity(tmp_path, False, 600, 10_000, git) == ("cleaned", 7000.0, None)


def test_a_changed_file_that_is_gone_counts_as_used_now(tmp_path):
    git = FakeGit(committed(1000), status=" D gone\n")
    assert idle_tree_activity(tmp_path, False, 600, 10_000, git) == ("cleaned", 10_000, None)
