import fcntl
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_warm_itest import warm_itest


@pytest.fixture
def repositories(tmp_path):
    source = tmp_path / "team" / "land" / "itest"
    dest = tmp_path / "dest"
    for repo in (source, dest):
        repo.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    return tmp_path / "team", source, dest


def test_free_lock_clones_source_and_is_held_during_clone(repositories):
    root, source, dest = repositories
    lock_path = root / "land" / "itest.lock"

    def clone(src, target):
        assert (src, target) == (source, dest)
        with lock_path.open("r+") as other:
            with pytest.raises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)

    copy = Mock(side_effect=clone)
    assert warm_itest(root, dest, copy) is True
    copy.assert_called_once_with(source, dest)
    assert not (dest / ".git" / "codeteam-prepared").exists()
    with lock_path.open("r+") as other:
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(other, fcntl.LOCK_UN)


def test_prepared_mark_is_copied_to_destination_git_dir(repositories):
    root, source, dest = repositories
    (source / ".git" / "codeteam-prepared").write_text("prepared state\n")
    clone = Mock()
    assert warm_itest(root, dest, clone) is True
    assert (dest / ".git" / "codeteam-prepared").read_text() == "prepared state\n"
    clone.assert_called_once_with(source, dest)


def test_held_lock_skips_clone_without_blocking(repositories, monkeypatch):
    root, source, dest = repositories
    (source / ".git" / "codeteam-prepared").write_text("do not copy")
    lock_path = root / "land" / "itest.lock"
    clone = Mock()
    flock = fcntl.flock
    with lock_path.open("a") as holder:
        flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)

        def nonblocking(file, operation):
            if operation & fcntl.LOCK_EX:
                assert operation & fcntl.LOCK_NB, "warm_itest must not wait for the itest lock"
            return flock(file, operation)

        monkeypatch.setattr(fcntl, "flock", nonblocking)
        assert warm_itest(root, dest, clone) is False
        clone.assert_not_called()
        assert not (dest / ".git" / "codeteam-prepared").exists()
        flock(holder, fcntl.LOCK_UN)


def test_missing_itest_skips_clone(tmp_path):
    root = tmp_path / "team"
    (root / "land").mkdir(parents=True)
    dest = tmp_path / "dest"
    clone = Mock()
    assert warm_itest(root, dest, clone) is False
    clone.assert_not_called()
    assert not dest.exists()


def test_missing_land_folder_is_not_created(tmp_path):
    root = tmp_path / "team"
    root.mkdir()
    dest = tmp_path / "dest"
    clone = Mock()
    assert warm_itest(root, dest, clone) is False
    clone.assert_not_called()
    assert not (root / "land").exists()
    assert not dest.exists()
