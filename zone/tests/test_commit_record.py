import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "bin" / "zone-tool"


@pytest.fixture
def repo(tmp_path):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CODETEAM_", "HERDR_", "GIT_", "ZONE_"))}
    env.update(HOME=str(tmp_path), GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, env=env,
                              text=True, capture_output=True, check=True).stdout.strip()

    def tool(*args, group=None):
        run_env = dict(env)
        if group is not None:
            run_env["CODETEAM_TEST_GROUP"] = group
        return subprocess.run([str(TOOL), *args], cwd=tmp_path, env=run_env,
                              text=True, capture_output=True)

    git("init", "-q")
    (tmp_path / "tracked.txt").write_text("original\n")
    git("add", "tracked.txt")
    git("commit", "-qm", "initial")
    return tmp_path, git, tool


def run_test(tool, key="k", result=0, cached=False, group=None):
    flags = ["--cached"] if cached else []
    return tool("test", *flags, "--key", key, "--", "sh", "-c", f"exit {result}", group=group)


def test_clean_pass_commit_record(repo):
    path, git, tool = repo
    assert run_test(tool).returncode == 0
    answer = tool("commit-record", "HEAD")
    assert answer.returncode == 0, answer.stderr
    assert answer.stdout.startswith("PASS ")
    assert len(answer.stdout.splitlines()) == 1
    assert git("rev-parse", "HEAD") in answer.stdout
    assert next(path.glob(".test-record-*.json")).name in answer.stdout


def test_tracked_change_is_not_clean(repo):
    path, _, tool = repo
    (path / "tracked.txt").write_text("modified\n")
    assert run_test(tool).returncode == 0
    answer = tool("commit-record", "HEAD")
    assert answer.returncode == 2, answer.stderr
    assert answer.stdout.startswith("none:")


@pytest.mark.parametrize("staged", [False, True])
def test_tracked_hash_ignore_change_is_not_clean(repo, staged):
    path, git, tool = repo
    (path / "Package.resolved").write_text("original\n")
    git("add", "Package.resolved")
    git("commit", "-qm", "track lockfile")
    (path / "Package.resolved").write_text("modified\n")
    if staged:
        git("add", "Package.resolved")
    assert run_test(tool).returncode == 0
    answer = tool("commit-record", "HEAD")
    assert answer.returncode == 2, answer.stderr
    assert answer.stdout.startswith("none:")


def test_untracked_hash_ignore_file_is_not_clean(repo):
    path, _, tool = repo
    (path / "Package.resolved").write_text("new\n")
    assert run_test(tool).returncode == 0
    answer = tool("commit-record", "HEAD")
    assert answer.returncode == 2, answer.stderr
    assert answer.stdout.startswith("none:")


def test_untracked_file_is_not_clean(repo):
    path, _, tool = repo
    (path / "untracked.txt").write_text("new\n")
    assert run_test(tool).returncode == 0
    answer = tool("commit-record", "HEAD")
    assert answer.returncode == 2, answer.stderr
    assert answer.stdout.startswith("none:")


def test_clean_failure_is_reported(repo):
    _, _, tool = repo
    assert run_test(tool, result=1).returncode == 1
    answer = tool("commit-record", "HEAD")
    assert answer.returncode == 1
    assert answer.stdout.startswith("FAIL ")
    assert len(answer.stdout.splitlines()) == 1


def test_record_belongs_to_original_commit(repo):
    _, git, tool = repo
    commit_a = git("rev-parse", "HEAD")
    assert run_test(tool).returncode == 0
    git("commit", "--allow-empty", "-qm", "second")
    commit_b = git("rev-parse", "HEAD")
    missing = tool("commit-record", commit_b)
    assert missing.returncode == 2, missing.stderr
    assert missing.stdout.startswith("none:")
    original = tool("commit-record", commit_a)
    assert original.returncode == 0, original.stderr
    assert original.stdout.startswith("PASS ")


def test_key_filter_and_any_failed_key(repo):
    _, _, tool = repo
    assert run_test(tool, key="k1").returncode == 0
    assert run_test(tool, key="k2", result=1).returncode == 1
    passing = tool("commit-record", "HEAD", "--key", "k1")
    failing = tool("commit-record", "HEAD", "--key", "k2")
    all_keys = tool("commit-record", "HEAD")
    assert passing.returncode == 0, passing.stderr
    assert passing.stdout.startswith("PASS ")
    assert failing.returncode == 1
    assert failing.stdout.startswith("FAIL ")
    assert all_keys.returncode == 1
    assert all_keys.stdout.startswith("FAIL ")


def test_integration_record_does_not_count(repo):
    _, _, tool = repo
    assert run_test(tool, group="integration").returncode == 0
    answer = tool("commit-record", "HEAD")
    assert answer.returncode == 2, answer.stderr
    assert answer.stdout.startswith("none:")


def test_cached_answer_counts_at_new_commit(repo):
    _, git, tool = repo
    assert run_test(tool, cached=True).returncode == 0
    git("commit", "--allow-empty", "-qm", "second")
    cached = run_test(tool, cached=True)
    assert cached.returncode == 0
    assert "already recorded" in cached.stdout
    answer = tool("commit-record", "HEAD")
    assert answer.returncode == 0, answer.stderr
    assert answer.stdout.startswith("PASS ")


def test_record_contains_commit_clean_and_default_group(repo):
    path, git, tool = repo
    assert run_test(tool).returncode == 0
    record = json.loads(next(path.glob(".test-record-*.json")).read_text())
    assert record.get("commit") == git("rev-parse", "HEAD")
    assert record.get("clean") is True
    assert record.get("group") == "unit"


def test_test_status_still_passes(repo):
    _, _, tool = repo
    assert run_test(tool).returncode == 0
    assert tool("test-status").returncode == 0


@pytest.mark.parametrize("result", ["HUNG", "TIMEOUT"])
def test_unfinished_record_fails_status_and_cannot_answer_cache(repo, result):
    path, _, tool = repo
    assert run_test(tool).returncode == 0
    record_path = next(path.glob(".test-record-*.json"))
    record = json.loads(record_path.read_text())
    # Synthesize these outcomes from a real record without waiting for a hung child.
    record["result"] = result
    record["exit"] = 124
    record_path.write_text(json.dumps(record))

    assert tool("test-status").returncode == 1
    rerun = tool("test", "--cached", "--key", "k", "--", "sh", "-c", "echo ran; exit 0")
    assert rerun.returncode == 0, rerun.stderr
    assert "ran" in rerun.stdout.splitlines()
    assert "already recorded" not in rerun.stdout


def test_clean_hung_commit_record_is_failure(repo):
    path, git, tool = repo
    assert run_test(tool).returncode == 0
    log = path / git("rev-parse", "--git-path", "zone-test-commits.jsonl")
    entry = json.loads(log.read_text().splitlines()[-1])
    assert entry["clean"] is True
    assert entry["group"] == "unit"
    # Append a HUNG outcome by hand to exercise lookup without a real hung process.
    entry.update(result="HUNG", exit=124)
    with log.open("a") as output:
        output.write(json.dumps(entry) + "\n")

    answer = tool("commit-record", "HEAD", "--key", "k")
    assert answer.returncode == 1, answer.stderr
    assert answer.stdout.startswith("HUNG ")
    assert len(answer.stdout.splitlines()) == 1


def test_newest_record_for_key_overrides_earlier_failure(repo):
    _, _, tool = repo
    assert run_test(tool, result=1).returncode == 1
    assert run_test(tool).returncode == 0
    answer = tool("commit-record", "HEAD", "--key", "k")
    assert answer.returncode == 0, answer.stderr
    assert answer.stdout.startswith("PASS ")


def test_unresolvable_commit_has_no_record(repo):
    _, _, tool = repo
    answer = tool("commit-record", "no-such-commit")
    assert answer.returncode == 2, answer.stderr
    assert answer.stdout.startswith("none:")


def test_empty_group_defaults_to_unit(repo):
    path, _, tool = repo
    assert run_test(tool, group="  ").returncode == 0
    record = json.loads(next(path.glob(".test-record-*.json")).read_text())
    assert record.get("group") == "unit"
