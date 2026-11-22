import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("segments", ROOT / "share" / "claude-hooks" / "segments.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
segments = module.segments


@pytest.mark.parametrize("command, expected", [
    ('cd H 2>&1 && git commit', [('cd H 2>&1', ['cd', 'H', '2>&1'], '&&'), ('git commit', ['git', 'commit'], '')]),
    ('a >&2; b', [('a >&2', ['a', '>&2'], ';'), ('b', ['b'], '')]),
    ('a >& f; b', [('a >& f', ['a', '>&', 'f'], ';'), ('b', ['b'], '')]),
    ('x &>f & y', [('x &>f', ['x', '&>f'], '&'), ('y', ['y'], '')]),
    ('x &>> f', [('x &>> f', ['x', '&>>', 'f'], '')]),
    ('a <&3 | b', [('a <&3', ['a', '<&3'], '|'), ('b', ['b'], '')]),
    ('a >|f | b', [('a >|f', ['a', '>|f'], '|'), ('b', ['b'], '')]),
    ('cd O & >/dev/null && g', [('cd O', ['cd', 'O'], '&'), ('>/dev/null', ['>/dev/null'], '&&'), ('g', ['g'], '')]),
    ("echo 'x >' & y", [("echo 'x >'", ['echo', 'x >'], '&'), ('y', ['y'], '')]),
    ('a & b', [('a', ['a'], '&'), ('b', ['b'], '')]),
    ('a |& b', [('a', ['a'], '|&'), ('b', ['b'], '')]),
    ('a && >f', [('a', ['a'], '&&'), ('>f', ['>f'], '')]),
    ('x 2>&1|y', [('x 2>&1', ['x', '2>&1'], '|'), ('y', ['y'], '')]),
    ("f --what 'a > b; c | d'", [("f --what 'a > b; c | d'", ['f', '--what', 'a > b; c | d'], '')]),
    ("f --what 'a 2>&1 b'", [("f --what 'a 2>&1 b'", ['f', '--what', 'a 2>&1 b'], '')]),
], ids=['fd-dup-and', 'fd-dup-semicolon', 'file-dup-semicolon', 'combined-background',
        'combined-append', 'input-fd-pipe', 'clobber-pipe', 'spaced-background-redirect',
        'quoted-operator-background', 'background', 'pipe-stderr', 'and-redirect',
        'fd-dup-adjacent-pipe', 'quoted-separators', 'quoted-fd-dup'])
def test_segments_examples(command, expected):
    assert segments(command) == expected


@pytest.mark.parametrize("command, expected", [
    ('cat>/opt/x', [('cat >/opt/x', ['cat', '>/opt/x'], '')]),
    ('echo x>/opt/x', [('echo x >/opt/x', ['echo', 'x', '>/opt/x'], '')]),
    ('a&>f', [('a &>f', ['a', '&>f'], '')]),
    ('a&>>f', [('a &>>f', ['a', '&>>f'], '')]),
    ('a>>f', [('a >>f', ['a', '>>f'], '')]),
    ('a>|f', [('a >|f', ['a', '>|f'], '')]),
    ('a>&2', [('a >&2', ['a', '>&2'], '')]),
    ('a<<<word', [('a <<<word', ['a', '<<<word'], '')]),
    ('a<<-EOF', [('a <<-EOF', ['a', '<<-EOF'], '')]),
    ('a<<EOF', [('a <<EOF', ['a', '<<EOF'], '')]),
    ('a<>f', [('a <>f', ['a', '<>f'], '')]),
    ('a<&3', [('a <&3', ['a', '<&3'], '')]),
    ('a<f', [('a <f', ['a', '<f'], '')]),
    ('a 2>/opt/x', [('a 2>/opt/x', ['a', '2>/opt/x'], '')]),
    ('a2>f', [('a2 >f', ['a2', '>f'], '')]),
    ('echo x >"/opt/a b"', [("echo x > '/opt/a b'", ['echo', 'x', '>', '/opt/a b'], '')]),
    ("echo x >'/opt/a b'", [("echo x > '/opt/a b'", ['echo', 'x', '>', '/opt/a b'], '')]),
    (r'echo x >/opt/a\ b', [("echo x > '/opt/a b'", ['echo', 'x', '>', '/opt/a b'], '')]),
    ('echo x >"/opt/x"', [('echo x > /opt/x', ['echo', 'x', '>', '/opt/x'], '')]),
    ("echo 'a>b'", [('echo a>b', ['echo', 'a>b'], '')]),
    ('git commit -m "x>y"', [('git commit -m x>y', ['git', 'commit', '-m', 'x>y'], '')]),
    (r'echo x\>y', [('echo x>y', ['echo', 'x>y'], '')]),
    ('echo ok # x>y', [('echo ok # x>y', ['echo', 'ok', '#', 'x>y'], '')]),
    ('cat <<EOF\nx>y\nEOF', [('cat <<EOF x>y EOF', ['cat', '<<EOF', 'x>y', 'EOF'], '')]),
], ids=[
    'glued-command', 'glued-argument', 'glued-combined', 'glued-combined-append',
    'glued-append', 'glued-clobber', 'glued-output-fd', 'glued-here-string',
    'glued-heredoc-strip', 'glued-heredoc', 'glued-read-write', 'glued-input-fd',
    'glued-input', 'word-start-fd', 'digits-inside-word', 'double-quoted-operand',
    'single-quoted-operand', 'backslash-operand', 'quoted-operand-no-space',
    'single-quoted-operator', 'double-quoted-operator', 'escaped-operator',
    'comment-operator', 'heredoc-body-operator',
])
def test_redirect_contract(command, expected):
    assert segments(command) == expected


def test_newline_separates_cd_and_commit():
    assert segments("cd X\ngit commit") == [
        ("cd X", ["cd", "X"], ";"), ("git commit", ["git", "commit"], "")]


def test_newline_inside_quotes_stays_in_one_part():
    assert [(words, sep) for _, words, sep in segments("echo 'a\nb'")] == [
        (["echo", "a\nb"], "")]


def test_heredoc_body_stays_in_part_before_following_command():
    assert segments("cat <<EOF\ncd X\nEOF\ngit commit") == [
        ("cat <<EOF cd X EOF", ["cat", "<<EOF", "cd", "X", "EOF"], ";"),
        ("git commit", ["git", "commit"], "")]


def test_backslash_newline_keeps_one_part():
    assert len(segments("a \\\nb")) == 1


def test_newline_after_and_preserves_separator():
    assert segments("a &&\nb") == [("a", ["a"], "&&"), ("b", ["b"], "")]


def test_newline_after_pipe_preserves_separator():
    assert segments("a |\nb") == [("a", ["a"], "|"), ("b", ["b"], "")]


def test_newline_after_semicolon_preserves_separator():
    assert segments("a;\nb") == [("a", ["a"], ";"), ("b", ["b"], "")]


@pytest.mark.parametrize("command", ["a\n", "\na", "\n\na\n\n"], ids=["trailing", "leading", "blank-lines"])
def test_leading_trailing_and_blank_lines_add_no_parts(command):
    assert segments(command) == segments("a") == [("a", ["a"], "")]


def test_fallback_heredoc_splits_glued_redirect():
    assert segments("cat>/opt/x <<EOF\nit's\nEOF") == [
        ('cat >/opt/x <<EOF', ['cat', '>/opt/x', '<<EOF'], ';'),
        ("it's", ['its'], ';'),
        ('EOF', ['EOF'], '')
    ]


def test_fallback_unbalanced_quote_removes_quote_from_words():
    assert segments('echo "x > /opt/y') == [
        ('echo "x > /opt/y', ['echo', 'x', '>', '/opt/y'], '')
    ]


@pytest.mark.parametrize("command, expected", [
    ('echo x 2>&1>/opt/x', [('echo x 2>&1 >/opt/x', ['echo', 'x', '2>&1', '>/opt/x'], '')]),
    ('echo x >&2>/opt/x', [('echo x >&2 >/opt/x', ['echo', 'x', '>&2', '>/opt/x'], '')]),
    ('a <&0>/opt/x', [('a <&0 >/opt/x', ['a', '<&0', '>/opt/x'], '')]),
    ('echo x 2>&1>"/opt/a b"', [("echo x 2>&1 > '/opt/a b'", ['echo', 'x', '2>&1', '>', '/opt/a b'], '')]),
], ids=['numbered-output-dup', 'output-dup', 'input-dup', 'quoted-target'])
def test_glued_redirect_after_descriptor_duplication_is_split(command, expected):
    assert segments(command) == expected


def test_fallback_quoted_spaced_target_and_heredoc_split_into_words_and_lines():
    assert segments('echo x >"/opt/a b" <<EOF\nit\'s\nEOF') == [
        ('echo x > "/opt/a b" <<EOF', ['echo', 'x', '>', '/opt/a', 'b', '<<EOF'], ';'),
        ("it's", ['its'], ';'),
        ('EOF', ['EOF'], '')
    ]
