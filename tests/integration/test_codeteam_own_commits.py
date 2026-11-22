"""Own commits include hand-resolved merges, with real git in a throwaway repository."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("CODETEAM_TEST_GROUP", "unit") != "integration",
                                reason="integration group only")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_own_commits import own_commits

IDENTITY = ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]


def git(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), *IDENTITY, *args], check=check, capture_output=True, text=True)


def commit(repo, name, text):
    (repo / name).write_text(text)
    git(repo, "add", name)
    git(repo, "commit", "-qm", text)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


@pytest.fixture
def history(tmp_path):
    git(tmp_path, "init", "-q", "-b", "work")
    root = commit(tmp_path, "conflict", "base\n")
    git(tmp_path, "checkout", "-qb", "side")
    side = commit(tmp_path, "conflict", "side\n")
    git(tmp_path, "checkout", "-q", "work")
    main = commit(tmp_path, "conflict", "main\n")
    result = git(tmp_path, "merge", "--no-ff", "side", check=False)
    assert result.returncode != 0
    merge = commit(tmp_path, "conflict", "resolved by hand\n")
    git(tmp_path, "checkout", "-qb", "clean-side")
    clean_side = commit(tmp_path, "side-file", "side file\n")
    git(tmp_path, "checkout", "-q", "work")
    main2 = commit(tmp_path, "main-file", "main file\n")
    git(tmp_path, "merge", "-q", "--no-ff", "--no-edit", "clean-side")
    clean = git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    return tmp_path, root, side, main, merge, clean_side, main2, clean


def test_clean_merge_is_dropped(history):
    repo, _, _, _, _, _, _, clean = history
    assert clean not in own_commits(repo, ["HEAD"])


def test_hand_resolved_merge_is_kept(history):
    repo, _, _, _, merge, _, _, _ = history
    assert merge in own_commits(repo, ["HEAD"])


def test_rev_list_order_is_preserved(history):
    repo, root, side, main, merge, clean_side, main2, _ = history
    expected = git(repo, "rev-list", "HEAD").stdout.splitlines()
    expected = [c for c in expected if c in {root, side, main, merge, clean_side, main2}]
    assert own_commits(repo, ["HEAD"]) == expected


def test_root_commit_is_kept(history):
    repo, root, *_ = history
    assert own_commits(repo, [root]) == [root]


def test_git_failure_raises(history):
    repo, *_ = history
    with pytest.raises(subprocess.CalledProcessError):
        own_commits(repo, ["no-such-revision"])
