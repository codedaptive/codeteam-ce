import importlib.util
import posixpath
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("git_folder", ROOT / "share" / "claude-hooks" / "git_folder.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
git_folder = module.git_folder


def resolve(path, cwd):
    return posixpath.normpath(posixpath.join(cwd, path))


def test_git_c_selects_the_resolved_folder():
    assert git_folder(["git", "-C", "repo", "commit"], "/work", resolve) == "/work/repo"


def test_chained_git_c_options_resolve_against_the_previous_folder():
    assert git_folder(["git", "-C", "one", "-C", "../two", "commit"], "/work", resolve) == "/work/two"


def test_a_path_to_git_is_recognized():
    assert git_folder(["/usr/bin/git", "-C", "repo", "commit"], "/work", resolve) == "/work/repo"


def test_a_non_git_command_ignores_c():
    assert git_folder(["other", "-C", "repo"], "/work", resolve) == "/work"


def test_git_without_c_keeps_the_folder():
    assert git_folder(["git", "commit"], "/work", resolve) == "/work"


def test_empty_words_keep_the_folder():
    assert git_folder([], "/work", resolve) == "/work"


def test_c_after_another_git_argument_is_not_leading():
    assert git_folder(["git", "status", "-C", "repo"], "/work", resolve) == "/work"
