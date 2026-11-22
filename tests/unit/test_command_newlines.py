import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "command_newlines", ROOT / "share" / "claude-hooks" / "command_newlines.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
command_newlines = module.command_newlines


@pytest.mark.parametrize("command, expected", [
    ("cd X\ngit commit", {4}),
    ("a\nb\nc", {1, 3}),
    ("a\n\nb", {1}),
    ("a # note\nb", {8}),
    ("a \\\n\nb", {4}),
], ids=["one-line-break", "each-line", "blank-line-once", "after-comment", "blank-line-after-continuation"])
def test_newline_after_a_command_ends_it(command, expected):
    assert command_newlines(command) == expected


@pytest.mark.parametrize("command", [
    "echo 'a\nb'",
    'echo "a\nb"',
    "a \\\nb",
    "a &&\nb",
    "a ||\nb",
    "a |\nb",
    "a;\nb",
    "a &\nb",
    "a\n",
    "\na",
    "\n\na\n\n",
    "cat <<EOF\ncd X\nEOF",
], ids=["single-quoted", "double-quoted", "continuation", "after-and", "after-or", "after-pipe", "after-semicolon",
        "after-background", "trailing", "leading", "blank-lines", "heredoc-only"])
def test_newline_that_ends_no_command(command):
    assert command_newlines(command) == set()


def test_heredoc_body_and_opening_newline_end_nothing_but_delimiter_line_does():
    assert command_newlines("cat <<EOF\ncd X\nEOF\ngit commit") == {18}


def test_dash_heredoc_ends_at_tab_indented_delimiter():
    assert command_newlines("cat <<-EOF\ncd X\n\tEOF\ngit commit") == {20}


def test_quoted_delimiter_heredoc_ends_at_bare_word():
    assert command_newlines("cat <<'EOF'\ncd X\nEOF\ngit commit") == {20}


def test_two_heredocs_on_one_line_end_after_the_second_delimiter():
    assert command_newlines("cat <<A <<B\nx\nA\ny\nB\nz") == {19}


def test_body_line_matching_the_delimiter_only_after_blanking_is_still_body():
    assert command_newlines("cat <<xx\nab\nxx\nz") == {14}


def test_escaped_heredoc_operator_opens_no_body():
    assert command_newlines("echo \\<<EOF\ngit commit\nEOF") == {11, 22}


def test_unclosed_heredoc_body_runs_to_the_end():
    assert command_newlines("cat <<EOF\ncd X\ngit commit") == set()
