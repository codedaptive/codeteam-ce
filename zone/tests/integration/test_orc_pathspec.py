"""Git pathspecs as the orchestrator guard reads them (D587)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "share/claude-hooks"))
import orc_pathspec as orc_pathspec_module
from orc_pathspec import orc_pathspec


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / "docs").mkdir()
    return root.resolve()


def test_plain_path_is_relative_to_cwd(repo):
    assert orc_pathspec("crates/cli/src/main.rs", str(repo)) == str(repo / "crates/cli/src/main.rs")


def test_dot_is_cwd(repo):
    assert orc_pathspec(".", str(repo / "docs")) == str(repo / "docs")


@pytest.mark.parametrize("arg", [":/", ":(top)"])
def test_top_pathspec_is_repo_root(repo, arg):
    assert orc_pathspec(arg, str(repo / "docs")) == str(repo)


@pytest.mark.parametrize("arg", [":/crates/cli", ":(top)crates/cli"])
def test_top_pathspec_with_path_is_root_relative(repo, arg):
    assert orc_pathspec(arg, str(repo / "docs")) == str(repo / "crates/cli")


def test_literal_pathspec_is_cwd_relative(repo):
    assert orc_pathspec(":(literal)crates/cli/src/main.rs", str(repo)) == str(repo / "crates/cli/src/main.rs")


def test_glob_pathspec_returns_literal_folder_prefix(repo):
    assert orc_pathspec(":(glob)crates/*", str(repo)) == str(repo / "crates")


@pytest.mark.parametrize("arg", ["crates/*/main.rs", "crates/*.rs"])
def test_plain_glob_returns_literal_folder_prefix(repo, arg):
    # git's default pathspec matching lets `*` cross `/`, so the whole literal prefix is named.
    assert orc_pathspec(arg, str(repo)) == str(repo / "crates")


def test_literal_magic_with_glob_characters_is_taken_as_written(repo):
    assert orc_pathspec(":(literal)crates/*", str(repo)) == str(repo / "crates/*")


def test_glob_without_folder_prefix_returns_cwd(repo):
    assert orc_pathspec(":(glob)*.rs", str(repo / "docs")) == str(repo / "docs")


def test_top_glob_returns_root_relative_literal_folder(repo):
    assert orc_pathspec(":(top,glob)crates/cli/**", str(repo / "docs")) == str(repo / "crates/cli")


@pytest.mark.parametrize("arg", [":!crates/cli", ":^crates/cli", ":(exclude)crates/cli"])
def test_excluded_pathspec_is_skipped(repo, arg):
    assert orc_pathspec(arg, str(repo)) is None


def test_top_without_repository_returns_cwd(tmp_path):
    cwd = tmp_path / "no-repo/docs"
    cwd.mkdir(parents=True)
    assert orc_pathspec(":/", str(cwd)) == str(cwd.resolve())


def test_nearest_jj_workspace_is_top(repo):
    workspace = repo / "wo/orc/x"
    (workspace / ".jj").mkdir(parents=True)
    (workspace / "docs").mkdir()
    assert orc_pathspec(":/", str(workspace / "docs")) == str(workspace)


def test_top_pathspec_uses_git_top_as_base(tmp_path, monkeypatch):
    cwd = tmp_path / "working"
    cwd.mkdir()
    monkeypatch.setattr(orc_pathspec_module, "git_top", lambda path: str(tmp_path / "chosen"))
    assert orc_pathspec(":/crates/cli", str(cwd)) == str(tmp_path / "chosen/crates/cli")
