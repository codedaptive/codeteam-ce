"""share/codeteam_unlanded_commits.py with real git on a throwaway repository (Orc-Codegraph #4653, D559): which commits
of a tree's HEAD landing does not hold. git on a repository the test made itself is no live service (rule 11), but the
function's subject is git's answer, so it is a zone integration test; the rule over those lists is unit-tested in
tests/unit/test_codeteam_carried_orders.py. Skipped unless CODETEAM_TEST_GROUP=integration."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("CODETEAM_TEST_GROUP", "unit") != "integration",
                                reason="integration group only; run with CODETEAM_TEST_GROUP=integration")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_unlanded_commits import unlanded_commits

IDENTITY = ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *IDENTITY, *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", name)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository on branch work at one base commit, with landing at the same commit."""
    git(tmp_path, "init", "-q", "-b", "work")
    commit(tmp_path, "base")
    git(tmp_path, "branch", "landing")
    return tmp_path


def test_the_trees_own_commits_newest_first(repo):
    first, second = commit(repo, "one"), commit(repo, "two")
    assert unlanded_commits(str(repo), "landing") == [second, first]


def test_commits_already_on_landing_are_left_out(repo):
    first = commit(repo, "one")
    second = commit(repo, "two")
    git(repo, "branch", "-f", "landing", first)
    assert unlanded_commits(str(repo), "landing") == [second]


def test_a_merged_branchs_commits_count_and_the_merge_does_not(repo):
    git(repo, "checkout", "-q", "-b", "host")
    hosts = commit(repo, "host")
    git(repo, "checkout", "-q", "work")
    own = commit(repo, "own")
    git(repo, "merge", "-q", "--no-ff", "--no-edit", "host")
    assert sorted(unlanded_commits(str(repo), "landing")) == sorted([own, hosts])


def test_a_detached_head_is_read_where_it_stands(repo):
    first = commit(repo, "one")
    commit(repo, "two")
    git(repo, "checkout", "-q", "--detach", first)
    assert unlanded_commits(str(repo), "landing") == [first]


def resolved_merge(repo):
    (repo / "base").write_text("base\n")
    git(repo, "add", "base")
    git(repo, "commit", "-qm", "prepare conflict")
    git(repo, "branch", "-f", "landing", "HEAD")
    git(repo, "checkout", "-qb", "side")
    (repo / "base").write_text("side\n")
    git(repo, "commit", "-qam", "side")
    git(repo, "checkout", "-q", "work")
    (repo / "base").write_text("work\n")
    git(repo, "commit", "-qam", "work")
    result = subprocess.run(["git", "-C", str(repo), *IDENTITY, "merge", "--no-ff", "side"], capture_output=True)
    assert result.returncode != 0
    (repo / "base").write_text("resolved\n")
    git(repo, "add", "base")
    git(repo, "commit", "-qm", "resolution")
    return git(repo, "rev-parse", "HEAD")


def test_hand_resolved_merge_counts(repo):
    merge = resolved_merge(repo)
    assert unlanded_commits(str(repo), "landing")[0] == merge


def test_other_orders_carried_check_still_refuses_shared_commits(repo, tmp_path):
    from types import SimpleNamespace
    from codeteam_carried_check import carried_check

    merge = resolved_merge(repo)
    tree = tmp_path / "carrying"
    git(repo, "worktree", "add", "-qb", "carrying", str(tree), merge)
    commit(tree, "extra")
    other = {"wo": "resolved", "tree": str(repo)}
    member = {"wo": "carrying", "tree": str(tree)}
    refusal = carried_check(SimpleNamespace(landing="landing"), [member], lambda _: [(None, other)], lambda *_: None)
    assert refusal is not None and "resolved" in refusal and "--with resolved" in refusal
    assert merge[:10] in refusal


def test_unrelated_order_does_not_carry_a_hand_resolved_merge(repo, tmp_path):
    from types import SimpleNamespace
    from codeteam_carried_check import carried_check

    resolved_merge(repo)
    other_tree = tmp_path / "unrelated"
    git(repo, "worktree", "add", "-qb", "unrelated", str(other_tree), "landing")
    commit(other_tree, "unrelated-change")
    resolved = {"wo": "resolved", "tree": str(repo)}
    unrelated = {"wo": "unrelated", "tree": str(other_tree)}
    assert carried_check(SimpleNamespace(landing="landing"), [unrelated],
                         lambda _: [(None, resolved)], lambda *_: None) is None


def test_no_tree_or_a_gone_one_holds_nothing(repo):
    commit(repo, "one")
    assert unlanded_commits(None, "landing") == []
    assert unlanded_commits("", "landing") == []
    assert unlanded_commits(str(repo / "gone"), "landing") == []
