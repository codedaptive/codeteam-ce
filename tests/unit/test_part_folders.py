import importlib.util
import posixpath
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("part_folders", ROOT / "share" / "claude-hooks" / "part_folders.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
part_folders = module.part_folders


def resolve(path, cwd):
    return posixpath.normpath(posixpath.join(cwd, path))


def resolve_links(path, cwd):
    links = {"/ct/link": "/outside/target", "/home/user/link": "/outside/target"}
    cwd = links.get(cwd, cwd)
    path = path.replace("~", "/home/user", 1) if path.startswith("~/") else path
    joined = posixpath.normpath(posixpath.join(cwd, path))
    return links.get(joined, joined)


def test_cd_through_link_then_parent_keeps_logical_parent():
    parts = [("cd link", ["cd", "link"], "&&"), ("cd ..", ["cd", ".."], "&&"),
             ("pwd", ["pwd"], "")]
    assert list(part_folders(parts, "/ct", "/home/user", resolve_links)) == [
        ("cd link", ["cd", "link"], ("/ct",)),
        ("cd ..", ["cd", ".."], ("/ct/link", "/outside/target")),
        ("pwd", ["pwd"], ("/ct", "/outside")),
    ]


def test_plain_cd_deduplicates_logical_and_physical_folders():
    parts = [("cd plain", ["cd", "plain"], ";"), ("pwd", ["pwd"], "")]
    assert list(part_folders(parts, "/ct", "/home/user", resolve_links)) == [
        ("cd plain", ["cd", "plain"], ("/ct",)), ("pwd", ["pwd"], ("/ct/plain",))]


def test_cd_expands_tilde_in_logical_folder():
    parts = [("cd ~/link", ["cd", "~/link"], ";"), ("pwd", ["pwd"], "")]
    assert list(part_folders(parts, "/ct", "/home/user", resolve_links)) == [
        ("cd ~/link", ["cd", "~/link"], ("/ct",)),
        ("pwd", ["pwd"], ("/home/user/link", "/outside/target"))]


def test_parts_without_cd_all_use_the_original_folder():
    parts = [("pwd", ["pwd"], ";"), ("git status", ["git", "status"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("pwd", ["pwd"], ("/work",)),
        ("git status", ["git", "status"], ("/work",)),
    ]


def test_later_relative_cd_is_resolved_against_the_previous_folder():
    parts = [("cd one", ["cd", "one"], ";"), ("cd ../two", ["cd", "../two"], "&&"), ("pwd", ["pwd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("cd one", ["cd", "one"], ("/work",)),
        ("cd ../two", ["cd", "../two"], ("/work/one",)),
        ("pwd", ["pwd"], ("/work/two",)),
    ]


def test_cd_with_only_options_sends_following_parts_home():
    parts = [("cd -P", ["cd", "-P"], ";"), ("pwd", ["pwd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("cd -P", ["cd", "-P"], ("/work",)), ("pwd", ["pwd"], ("/home/user",))
    ]


def test_bare_cd_sends_following_parts_home():
    parts = [("cd", ["cd"], ";"), ("pwd", ["pwd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("cd", ["cd"], ("/work",)), ("pwd", ["pwd"], ("/home/user",))
    ]


def test_cd_dash_leaves_the_folder_unchanged():
    parts = [("cd -", ["cd", "-"], ";"), ("pwd", ["pwd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("cd -", ["cd", "-"], ("/work",)), ("pwd", ["pwd"], ("/work",))
    ]


def test_assignment_prefixes_do_not_hide_cd():
    parts = [("VAR=x cd repo", ["VAR=x", "cd", "repo"], ";"), ("pwd", ["pwd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("VAR=x cd repo", ["VAR=x", "cd", "repo"], ("/work",)), ("pwd", ["pwd"], ("/work/repo",))
    ]


@pytest.mark.parametrize("words", [
    ["env", "cd", "one"],
    ["nohup", "cd", "one"],
    ["nice", "-n", "5", "cd", "one"],
    ["exec", "cd", "one"],
    ["timeout", "5", "cd", "one"],
    ["gtimeout", "5", "cd", "one"],
    ["command", "-p", "env", "cd", "one"],
    ["time", "-p", "nohup", "cd", "one"],
    ["A=1", "env", "B=2", "cd", "one"],
])
def test_external_wrapper_cd_does_not_move_shell(words):
    parts = [("wrapped cd", words, ";"), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("wrapped cd", words, ("/work",)), ("cmd", ["cmd"], ("/work",))
    ]


@pytest.mark.parametrize("words", [
    ["command", "cd", "one"],
    ["command", "-p", "--", "cd", "one"],
    ["time", "cd", "one"],
    ["time", "-p", "--", "cd", "one"],
    ["A=1", "command", "-p", "time", "-p", "cd", "one"],
])
def test_shell_wrapper_cd_may_move_shell(words):
    parts = [("wrapped cd", words, ";"), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("wrapped cd", words, ("/work",)), ("cmd", ["cmd"], ("/work", "/work/one"))
    ]


def test_cd_uses_the_last_directory_after_ignoring_options():
    parts = [("cd first -P second", ["cd", "first", "-P", "second"], ";"), ("pwd", ["pwd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("cd first -P second", ["cd", "first", "-P", "second"], ("/work",)),
        ("pwd", ["pwd"], ("/work/second",)),
    ]


def test_empty_parts_yield_nothing():
    assert list(part_folders([], "/work", "/home/user", resolve)) == []


def test_cd_before_pipe_does_not_change_later_folder():
    parts = [("cd one", ["cd", "one"], "|"), ("git commit", ["git", "commit"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("cd one", ["cd", "one"], ("/work",)),
        ("git commit", ["git", "commit"], ("/work",)),
    ]


def test_cd_after_pipe_does_not_change_later_folder():
    parts = [("pwd", ["pwd"], "|"), ("cd one", ["cd", "one"], ";"),
             ("git commit", ["git", "commit"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("pwd", ["pwd"], ("/work",)),
        ("cd one", ["cd", "one"], ("/work",)),
        ("git commit", ["git", "commit"], ("/work",)),
    ]


def test_background_cd_does_not_change_later_folder():
    parts = [("cd one", ["cd", "one"], "&"), ("git commit", ["git", "commit"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("cd one", ["cd", "one"], ("/work",)),
        ("git commit", ["git", "commit"], ("/work",)),
    ]


def test_cd_before_pipe_with_stderr_does_not_change_later_folder():
    parts = [("cd one", ["cd", "one"], "|&"), ("cat", ["cat"], ";"), ("pwd", ["pwd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("cd one", ["cd", "one"], ("/work",)),
        ("cat", ["cat"], ("/work",)),
        ("pwd", ["pwd"], ("/work",)),
    ]


def test_background_command_after_cd_runs_in_changed_folder():
    parts = [("cd one", ["cd", "one"], "&&"), ("git commit", ["git", "commit"], "&"), ("", [], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("cd one", ["cd", "one"], ("/work",)),
        ("git commit", ["git", "commit"], ("/work/one",)),
        ("", [], ("/work",)),
    ]


def test_cd_or_runs_one_part_in_original_folder_then_carries_cd():
    parts = [("cd one", ["cd", "one"], "||"), ("exit 1", ["exit", "1"], ";"),
             ("git commit", ["git", "commit"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("cd one", ["cd", "one"], ("/work",)),
        ("exit 1", ["exit", "1"], ("/work",)),
        ("git commit", ["git", "commit"], ("/work/one",)),
    ]


def test_pipeline_after_cd_runs_both_parts_in_changed_folder():
    parts = [("cd one", ["cd", "one"], ";"), ("git a", ["git", "a"], "|"),
             ("git b", ["git", "b"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("cd one", ["cd", "one"], ("/work",)),
        ("git a", ["git", "a"], ("/work/one",)),
        ("git b", ["git", "b"], ("/work/one",)),
    ]


def test_cd_after_stderr_pipe_does_not_carry():
    parts = [("a", ["a"], "|&"), ("cd one", ["cd", "one"], ";"), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("a", ["a"], ("/work",)), ("cd one", ["cd", "one"], ("/work",)), ("cmd", ["cmd"], ("/work",))]


def test_cd_or_cd_keeps_first_folder():
    parts = [("cd one", ["cd", "one"], "||"), ("cd two", ["cd", "two"], ";"), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("cd one", ["cd", "one"], ("/work",)), ("cd two", ["cd", "two"], ("/work",)), ("cmd", ["cmd"], ("/work/one",))]


def test_cd_or_two_cds_keeps_first_folder():
    parts = [("cd one", ["cd", "one"], "||"), ("cd two", ["cd", "two"], "||"),
             ("cd three", ["cd", "three"], ";"), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("cd one", ["cd", "one"], ("/work",)), ("cd two", ["cd", "two"], ("/work",)),
        ("cd three", ["cd", "three"], ("/work",)), ("cmd", ["cmd"], ("/work/one",))]


def test_cd_or_cd_or_commit_judges_commit_before_first_cd():
    parts = [("cd one", ["cd", "one"], "||"), ("cd two", ["cd", "two"], "||"),
             ("git commit", ["git", "commit"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("cd one", ["cd", "one"], ("/work",)), ("cd two", ["cd", "two"], ("/work",)),
        ("git commit", ["git", "commit"], ("/work",))]


def test_cd_or_pipeline_judges_both_parts_before_cd_then_carries_cd():
    parts = [("cd one", ["cd", "one"], "||"), ("a", ["a"], "|"), ("b", ["b"], ";"),
             ("git commit", ["git", "commit"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("cd one", ["cd", "one"], ("/work",)), ("a", ["a"], ("/work",)), ("b", ["b"], ("/work",)),
        ("git commit", ["git", "commit"], ("/work/one",))]


def test_cd_or_command_and_command_carries_first_cd():
    parts = [("cd one", ["cd", "one"], "||"), ("a", ["a"], "&&"), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("cd one", ["cd", "one"], ("/work",)), ("a", ["a"], ("/work",)), ("cmd", ["cmd"], ("/work/one",))]


def test_command_or_cd_widens_folders_after_list():
    parts = [("a", ["a"], "||"), ("cd one", ["cd", "one"], ";"), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("a", ["a"], ("/work",)), ("cd one", ["cd", "one"], ("/work",)), ("cmd", ["cmd"], ("/work", "/work/one"))]


def test_command_and_cd_widens_folders_after_list():
    parts = [("a", ["a"], "&&"), ("cd one", ["cd", "one"], ";"), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("a", ["a"], ("/work",)), ("cd one", ["cd", "one"], ("/work",)), ("cmd", ["cmd"], ("/work", "/work/one"))]


def test_cd_and_background_command_restores_list_start():
    parts = [("cd one", ["cd", "one"], "&&"), ("a", ["a"], "&"), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("cd one", ["cd", "one"], ("/work",)), ("a", ["a"], ("/work/one",)), ("cmd", ["cmd"], ("/work",))]


def test_background_after_semicolon_keeps_earlier_cd():
    parts = [("cd one", ["cd", "one"], ";"), ("a", ["a"], "&"), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("cd one", ["cd", "one"], ("/work",)), ("a", ["a"], ("/work/one",)), ("cmd", ["cmd"], ("/work/one",))]


def test_cd_or_background_restores_list_start():
    parts = [("cd one", ["cd", "one"], "||"), ("a", ["a"], "&"), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("cd one", ["cd", "one"], ("/work",)), ("a", ["a"], ("/work",)), ("cmd", ["cmd"], ("/work",))]


def test_cd_skips_fd_duplication():
    parts = [("cd one 2>&1", ["cd", "one", "2>&1"], ";"), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("cd one 2>&1", ["cd", "one", "2>&1"], ("/work",)), ("cmd", ["cmd"], ("/work/one",))]


def test_cd_skips_glued_write_redirect():
    parts = [("cd one >/dev/null", ["cd", "one", ">/dev/null"], ";"), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("cd one >/dev/null", ["cd", "one", ">/dev/null"], ("/work",)), ("cmd", ["cmd"], ("/work/one",))]


def test_cd_skips_separate_write_redirect_operand():
    parts = [("cd one 2> /dev/null", ["cd", "one", "2>", "/dev/null"], ";"), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("cd one 2> /dev/null", ["cd", "one", "2>", "/dev/null"], ("/work",)), ("cmd", ["cmd"], ("/work/one",))]


def test_cd_with_only_redirect_goes_home():
    parts = [("cd 2>/dev/null", ["cd", "2>/dev/null"], ";"), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("cd 2>/dev/null", ["cd", "2>/dev/null"], ("/work",)), ("cmd", ["cmd"], ("/home/user",))]


def test_conditional_and_cd_widens_after_semicolon():
    parts = [("false", ["false"], "&&"), ("cd one", ["cd", "one"], ";"), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("false", ["false"], ("/work",)), ("cd one", ["cd", "one"], ("/work",)),
        ("cmd", ["cmd"], ("/work", "/work/one"))]


def test_conditional_or_cd_widens_after_semicolon():
    parts = [("true", ["true"], "||"), ("cd one", ["cd", "one"], ";"), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("true", ["true"], ("/work",)), ("cd one", ["cd", "one"], ("/work",)),
        ("cmd", ["cmd"], ("/work", "/work/one"))]


def test_conditional_cd_and_command_uses_cd_folder_alone():
    parts = [("a", ["a"], "&&"), ("cd one", ["cd", "one"], "&&"), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("a", ["a"], ("/work",)), ("cd one", ["cd", "one"], ("/work",)),
        ("cmd", ["cmd"], ("/work/one",))]


def test_conditional_cd_and_command_then_semicolon_widens():
    parts = [("a", ["a"], "&&"), ("cd one", ["cd", "one"], "&&"),
             ("b", ["b"], ";"), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("a", ["a"], ("/work",)), ("cd one", ["cd", "one"], ("/work",)),
        ("b", ["b"], ("/work/one",)), ("cmd", ["cmd"], ("/work", "/work/one"))]


def test_conditional_cd_and_command_then_or_widens():
    parts = [("a", ["a"], "&&"), ("cd one", ["cd", "one"], "&&"),
             ("b", ["b"], "||"), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("a", ["a"], ("/work",)), ("cd one", ["cd", "one"], ("/work",)),
        ("b", ["b"], ("/work/one",)), ("cmd", ["cmd"], ("/work", "/work/one"))]


def test_conditional_cd_in_pipeline_moves_nothing():
    parts = [("a", ["a"], "&&"), ("cd one", ["cd", "one"], "|"),
             ("b", ["b"], ";"), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("a", ["a"], ("/work",)), ("cd one", ["cd", "one"], ("/work",)),
        ("b", ["b"], ("/work",)), ("cmd", ["cmd"], ("/work",))]


def test_conditional_cd_background_restores_list_start():
    parts = [("a", ["a"], "&&"), ("cd one", ["cd", "one"], "&"), ("b", ["b"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("a", ["a"], ("/work",)), ("cd one", ["cd", "one"], ("/work",)),
        ("b", ["b"], ("/work",))]


def test_conditional_cd_or_failure_chain_then_widens():
    parts = [("a", ["a"], "&&"), ("cd one", ["cd", "one"], "||"),
             ("b", ["b"], ";"), ("c", ["c"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("a", ["a"], ("/work",)), ("cd one", ["cd", "one"], ("/work",)),
        ("b", ["b"], ("/work",)), ("c", ["c"], ("/work", "/work/one"))]


def test_conditional_cd_or_cd_carries_both_destinations():
    parts = [("a", ["a"], "&&"), ("cd one", ["cd", "one"], "||"),
             ("cd two", ["cd", "two"], ";"), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("a", ["a"], ("/work",)), ("cd one", ["cd", "one"], ("/work",)),
        ("cd two", ["cd", "two"], ("/work",)),
        ("cmd", ["cmd"], ("/work", "/work/one", "/work/two"))]


def test_conditional_cd_or_two_cds_carries_all_destinations():
    parts = [("a", ["a"], "&&"), ("cd one", ["cd", "one"], "||"),
             ("cd two", ["cd", "two"], "||"), ("cd three", ["cd", "three"], ";"),
             ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("a", ["a"], ("/work",)), ("cd one", ["cd", "one"], ("/work",)),
        ("cd two", ["cd", "two"], ("/work",)), ("cd three", ["cd", "three"], ("/work",)),
        ("cmd", ["cmd"], ("/work", "/work/one", "/work/two", "/work/three"))]


def test_conditional_cd_or_cd_or_commit_judges_commit_before_first_cd():
    parts = [("a", ["a"], "&&"), ("cd one", ["cd", "one"], "||"),
             ("cd two", ["cd", "two"], "||"), ("git commit", ["git", "commit"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("a", ["a"], ("/work",)), ("cd one", ["cd", "one"], ("/work",)),
        ("cd two", ["cd", "two"], ("/work",)), ("git commit", ["git", "commit"], ("/work",))]


def test_conditional_cd_or_piped_cd_does_not_carry_piped_destination():
    parts = [("a", ["a"], "&&"), ("cd one", ["cd", "one"], "||"),
             ("cd two", ["cd", "two"], "|"), ("b", ["b"], ";"), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("a", ["a"], ("/work",)), ("cd one", ["cd", "one"], ("/work",)),
        ("cd two", ["cd", "two"], ("/work",)), ("b", ["b"], ("/work",)),
        ("cmd", ["cmd"], ("/work", "/work/one"))]


def test_relative_cd_resolves_against_each_widened_folder():
    parts = [("true", ["true"], "&&"), ("cd one", ["cd", "one"], ";"),
             ("cd two", ["cd", "two"], ";"), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("true", ["true"], ("/work",)), ("cd one", ["cd", "one"], ("/work",)),
        ("cd two", ["cd", "two"], ("/work", "/work/one")),
        ("cmd", ["cmd"], ("/work/two", "/work/one/two"))]


def test_later_conditional_cd_adds_to_pending_union():
    parts = [("a", ["a"], "&&"), ("cd one", ["cd", "one"], "&&"),
             ("cd two", ["cd", "two"], ";"), ("c", ["c"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("a", ["a"], ("/work",)), ("cd one", ["cd", "one"], ("/work",)),
        ("cd two", ["cd", "two"], ("/work/one",)),
        ("c", ["c"], ("/work", "/work/one", "/work/one/two"))]


def test_conditional_cd_failure_chain_includes_earlier_pending_folders():
    parts = [("a", ["a"], "&&"), ("cd one", ["cd", "one"], "&&"),
             ("cd two", ["cd", "two"], "||"), ("b", ["b"], ";"), ("c", ["c"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("a", ["a"], ("/work",)), ("cd one", ["cd", "one"], ("/work",)),
        ("cd two", ["cd", "two"], ("/work/one",)),
        ("b", ["b"], ("/work", "/work/one")),
        ("c", ["c"], ("/work", "/work/one", "/work/one/two"))]


def test_widened_folders_deduplicate_in_first_seen_order():
    parts = [("a", ["a"], "&&"), ("cd .", ["cd", "."], ";"), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("a", ["a"], ("/work",)), ("cd .", ["cd", "."], ("/work",)),
        ("cmd", ["cmd"], ("/work",))]


@pytest.mark.parametrize("words, expected", [
    (["builtin", "cd", "one"], ("/work/one",)),
    (["command", "builtin", "cd", "one"], ("/work", "/work/one")),
], ids=["builtin", "command-builtin"])
def test_builtin_cd_depends_on_preceding_wrappers(words, expected):
    parts = [("wrapped cd", words, ";"), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("wrapped cd", words, ("/work",)), ("cmd", ["cmd"], expected)]


@pytest.mark.parametrize("separator", [";", "&&", "||"], ids=["semicolon", "and", "or"])
def test_negated_cd_widens_following_folders(separator):
    parts = [("! cd one", ["!", "cd", "one"], separator), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("! cd one", ["!", "cd", "one"], ("/work",)),
        ("cmd", ["cmd"], ("/work", "/work/one"))]


def test_negated_cd_or_does_not_start_failure_chain():
    parts = [("! cd one", ["!", "cd", "one"], "||"),
             ("cmd", ["cmd"], ";"), ("last", ["last"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("! cd one", ["!", "cd", "one"], ("/work",)),
        ("cmd", ["cmd"], ("/work", "/work/one")),
        ("last", ["last"], ("/work", "/work/one"))]


def test_negated_env_cd_does_not_move_shell():
    parts = [("! env cd one", ["!", "env", "cd", "one"], ";"), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("! env cd one", ["!", "env", "cd", "one"], ("/work",)),
        ("cmd", ["cmd"], ("/work",))]


@pytest.mark.parametrize("words", [
    ["time", "-p", "cd", "one"],
    ["time", "--", "cd", "one"],
    ["command", "-p", "cd", "one"],
    ["builtin", "--", "cd", "one"],
    ["noglob", "cd", "one"],
    ["nocorrect", "cd", "one"],
    ["builtin", "command", "cd", "one"],
], ids=["time-p", "time-end-options", "command-p", "builtin-end-options",
        "noglob", "nocorrect", "builtin-command"])
@pytest.mark.parametrize("separator", [";", "&&", "||"], ids=["semicolon", "and", "or"])
def test_uncertain_wrapper_cd_widens_after_each_list_separator(words, separator):
    parts = [("wrapped cd", words, separator), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("wrapped cd", words, ("/work",)), ("cmd", ["cmd"], ("/work", "/work/one"))]


def test_assignment_before_builtin_cd_moves_shell():
    words = ["A=1", "builtin", "cd", "one"]
    parts = [("wrapped cd", words, ";"), ("cmd", ["cmd"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("wrapped cd", words, ("/work",)), ("cmd", ["cmd"], ("/work/one",))]


def test_uncertain_wrapper_cd_or_does_not_start_failure_chain():
    words = ["command", "cd", "one"]
    parts = [("wrapped cd", words, "||"), ("cmd", ["cmd"], ";"), ("last", ["last"], "")]
    assert list(part_folders(parts, "/work", "/home/user", resolve)) == [
        ("wrapped cd", words, ("/work",)),
        ("cmd", ["cmd"], ("/work", "/work/one")),
        ("last", ["last"], ("/work", "/work/one"))]

