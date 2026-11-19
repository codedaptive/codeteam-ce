import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("command_words", ROOT / "share" / "claude-hooks" / "command_words.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
command_words = module.command_words


def test_assignment_prefixes_are_dropped_before_the_command():
    assert command_words(["VAR=x", "OTHER=y", "git", "A=b"]) == ["git", "A=b"]


def test_path_like_words_with_equals_are_kept():
    assert command_words(["VAR=x", "/bin/a=b", "arg"]) == ["/bin/a=b", "arg"]
    assert command_words(["VAR=x", "~/a=b", "arg"]) == ["~/a=b", "arg"]
    assert command_words(["VAR=x", "./a=b", "arg"]) == ["./a=b", "arg"]


def test_all_assignment_prefixes_leave_no_command():
    assert command_words(["A=1", "B=2"]) == []


def test_empty_words_leave_no_command():
    assert command_words([]) == []


@pytest.mark.parametrize("words, expected", [
    (["env", "CODETEAM_SESSION=Kong", "/x/bin/codeteam-land", "m", "doc-fix"],
     ["/x/bin/codeteam-land", "m", "doc-fix"]),
    (["/usr/bin/env", "-i", "A=1", "rm", "f"], ["rm", "f"]),
    (["env", "-", "rm", "f"], ["rm", "f"]),
    (["env", "-0", "rm", "f"], ["rm", "f"]),
    (["env", "-v", "rm", "f"], ["rm", "f"]),
    (["env", "--ignore-environment", "rm", "f"], ["rm", "f"]),
    (["env", "-u", "HOME", "git", "commit"], ["git", "commit"]),
    (["env", "-uHOME", "git", "commit"], ["git", "commit"]),
    (["env", "--unset=HOME", "git", "commit"], ["git", "commit"]),
    (["env", "--unset", "HOME", "git", "commit"], ["git", "commit"]),
    (["env", "--", "A=1", "rm", "f"], ["rm", "f"]),
    (["nohup", "--", "rm", "x"], ["rm", "x"]),
    (["nice", "-n", "5", "make"], ["make"]),
    (["nice", "-n5", "make"], ["make"]),
    (["nice", "-5", "make"], ["make"]),
    (["nice", "--adjustment=5", "make"], ["make"]),
    (["nice", "--", "make"], ["make"]),
    (["time", "-p", "rm", "x"], ["rm", "x"]),
    (["time", "--", "rm", "x"], ["rm", "x"]),
    (["command", "-p", "rm", "x"], ["rm", "x"]),
    (["command", "--", "rm", "x"], ["rm", "x"]),
    (["exec", "-a", "name", "rm", "x"], ["rm", "x"]),
    (["exec", "-c", "rm", "x"], ["rm", "x"]),
    (["exec", "-l", "rm", "x"], ["rm", "x"]),
    (["exec", "-cl", "rm", "x"], ["rm", "x"]),
    (["exec", "-lc", "rm", "x"], ["rm", "x"]),
    (["exec", "--", "rm", "x"], ["rm", "x"]),
    (["timeout", "600", "codeteam-land", "q"], ["codeteam-land", "q"]),
    (["gtimeout", "1.5h", "rm", "x"], ["rm", "x"]),
    (["timeout", "--foreground", "5s", "rm", "x"], ["rm", "x"]),
    (["timeout", "--preserve-status", "5m", "rm", "x"], ["rm", "x"]),
    (["timeout", "-v", "5h", "rm", "x"], ["rm", "x"]),
    (["timeout", "--verbose", "5d", "rm", "x"], ["rm", "x"]),
    (["timeout", "-s", "TERM", "5", "rm", "x"], ["rm", "x"]),
    (["timeout", "--signal=TERM", "5", "rm", "x"], ["rm", "x"]),
    (["timeout", "-k", "2s", "5", "rm", "x"], ["rm", "x"]),
    (["timeout", "--kill-after=2s", "5", "rm", "x"], ["rm", "x"]),
    (["nohup", "nice", "-n", "5", "make"], ["make"]),
    (["A=1", "env", "B=2", "nohup", "rm", "x"], ["rm", "x"]),
    (["env", "A=1", "./a=b", "arg"], ["./a=b", "arg"]),
    (["env", "A=1", "/bin/a=b", "arg"], ["/bin/a=b", "arg"]),
    (["env", "A=1", "~/a=b", "arg"], ["~/a=b", "arg"]),
])
def test_unwraps_program_runners(words, expected):
    assert command_words(words) == expected


@pytest.mark.parametrize("words, expected", [
    (["command", "-v", "rm"], ["command", "-v", "rm"]),
    (["command", "-V", "rm"], ["command", "-V", "rm"]),
    (["env", "-S", "rm x"], ["env", "-S", "rm x"]),
    (["env", "-C", "dir", "rm", "x"], ["env", "-C", "dir", "rm", "x"]),
    (["time", "-o", "f", "rm", "x"], ["time", "-o", "f", "rm", "x"]),
    (["nice", "--foo", "rm", "x"], ["nice", "--foo", "rm", "x"]),
    (["nohup", "--foo", "rm", "x"], ["nohup", "--foo", "rm", "x"]),
    (["command", "--foo", "rm", "x"], ["command", "--foo", "rm", "x"]),
    (["exec", "--foo", "rm", "x"], ["exec", "--foo", "rm", "x"]),
    (["timeout", "--foo", "5", "rm", "x"], ["timeout", "--foo", "5", "rm", "x"]),
    (["timeout", "soon", "rm", "x"], ["timeout", "soon", "rm", "x"]),
    (["timeout", "5w", "rm", "x"], ["timeout", "5w", "rm", "x"]),
    (["timeout", "-v"], ["timeout", "-v"]),
    (["env"], ["env"]),
    (["env", "A=1"], ["env", "A=1"]),
    (["nohup"], ["nohup"]),
    (["nice", "-n", "5"], ["nice", "-n", "5"]),
    (["time", "-p"], ["time", "-p"]),
    (["command", "-p"], ["command", "-p"]),
    (["exec", "-c"], ["exec", "-c"]),
    (["timeout", "600"], ["timeout", "600"]),
    (["A=1", "nohup", "env", "-S", "rm x"], ["env", "-S", "rm x"]),
    (["env", "A=1", "nohup"], ["nohup"]),
])
def test_keeps_wrapper_when_it_cannot_run_a_program(words, expected):
    assert command_words(words) == expected


@pytest.mark.parametrize("words, expected", [
    (["builtin", "cd", "x"], ["cd", "x"]),
    (["!", "rm", "x"], ["rm", "x"]),
    (["builtin"], ["builtin"]),
    (["!"], ["!"]),
    (["!", "env", "A=1", "rm", "x"], ["rm", "x"]),
], ids=["builtin", "negation", "bare-builtin", "bare-negation", "negated-env"])
def test_shell_builtin_and_negation_wrappers(words, expected):
    assert command_words(words) == expected


@pytest.mark.parametrize("words, expected", [
    (["builtin", "--", "cd", "x"], ["cd", "x"]),
    (["noglob", "cd", "x"], ["cd", "x"]),
    (["nocorrect", "rm", "x"], ["rm", "x"]),
    (["noglob"], ["noglob"]),
], ids=["builtin-end-options", "noglob", "nocorrect", "bare-noglob"])
def test_shell_wrappers_and_builtin_option_terminator(words, expected):
    assert command_words(words) == expected
