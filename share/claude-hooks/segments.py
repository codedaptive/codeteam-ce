"""The parts of a compound shell command, split where the shell splits it; harness-guard.py uses it."""
import os
import re
import shlex
import sys

sys.dont_write_bytecode = True          # no __pycache__ beside the hooks in production's checkout
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shell_text import code_only

_SEPARATORS = {";", "&&", "||", "|", "&", "|&"}
_OPERATOR = re.compile(r"&>>?|>>|>\||>&|>|<<<|<<-|<<|<>|<&|<")
_OPERAND = re.compile(r"[^\s;&|<>]*")          # an operand runs to whitespace, a separator or the next redirect
_WORD_END = " \t\n;&|"                         # what ends the word before an operator
_NO_QUOTES = str.maketrans("", "", "'\"")


def segments(cmd: str) -> list[tuple[str, list[str], str]]:
    """The parts of a compound command as (seg, words, sep), `sep` the separator after the part ("" for the last) and
    `seg` its words joined by one space (a word holding whitespace shell-quoted). A separator inside quotes (a
    finding's --what text quoting `a > b; c | d`) stays in its word, and an `&` or `|` that is part of a
    redirect operator (`2>&1`, `<&3`, `&>f`, `>|f`) is not a separator; a redirect glued to a word (`cat>f`) or to a
    descriptor duplication (`2>&1>f`) is its own word. When shlex cannot read the command (an unbalanced quote, an
    apostrophe in a heredoc body or a `#` comment, `$'it\\'s'`), a space goes wherever _gaps puts one, so a glued
    redirect is still its own word (after an unbalanced quote code_only blanks the rest, so none is added there); the
    text is split on every `&&`, `||`, `;`, `|` and newline, quoted or not, a newline's part taking the separator ";".
    There `seg` is the piece as split, and its words are the piece split at whitespace, each with every `'` and `"`
    removed, empty words dropped: a quoted operand is split at its spaces, so `>"/opt/a b"` gives `>`, `/opt/a`, `b`."""
    try:
        lex = shlex.shlex(_escape_redirects(cmd), posix=True, punctuation_chars=";&|")
        lex.whitespace_split = True
        lex.commenters = ""             # a mid-word '#' must not hide what follows (Nagatha)
        tokens = list(lex)
    except ValueError:
        return _fallback(cmd)
    out, words, raw = [], [], []
    for tok in tokens:
        if tok in _SEPARATORS:
            out.append((" ".join(raw), words, tok))
            words, raw = [], []
        else:
            words.append(tok)
            raw.append(shlex.quote(tok) if tok != tok.strip() or " " in tok else tok)
    out.append((" ".join(raw), words, ""))
    return out


def _fallback(cmd):
    """The parts of a command shlex cannot read, split as segments' docstring says."""
    gaps = _gaps(code_only(cmd))
    pieces = re.split(r"(&&|\|\||;|\||\n)", "".join((" " if i in gaps else "") + c for i, c in enumerate(cmd)))
    seps = [";" if sep == "\n" else sep for sep in pieces[1::2]] + [""]
    return [(seg, [w for w in seg.translate(_NO_QUOTES).split() if w], sep) for seg, sep in zip(pieces[::2], seps)]


def _escape_redirects(cmd):
    """cmd with a backslash before each `&` or `|` that touches a `<` or `>` outside quotes as part of its operator
    (`>&`, `<&`, `&>`, `>|`), so shlex reads it as a word character, and a space wherever _gaps puts one, so each
    redirect is a word of its own. shlex keeps no positions, so this is decided on the raw text: `cd X & >f` keeps
    its separator."""
    code = code_only(cmd)
    gaps = _gaps(code)
    return "".join((" " if i in gaps else "") + ("\\" + c if _in_operator(code, i) else c) for i, c in enumerate(cmd))


def _gaps(code):
    """The indexes in `code` a space goes before: a redirect operator glued to the word before it (`cat>f`), and the
    operand glued after one when it holds a quote or a backslash (`>"a b"`), since redirects.py takes a word holding
    whitespace for quoted text and would miss the operator in it. One operator per run: `>>` is one, not two."""
    gaps, i = set(), 0
    while i < len(code):
        m = _OPERATOR.match(code, i)
        if not m or _escaped(code, i) or code[i - 1:i + 1] == "&&":
            i += 1
            continue
        if _glued_before(code, i, m.group()):
            gaps.add(i)
        if any(c in "'\"\\" for c in _OPERAND.match(code, m.end()).group()):
            gaps.add(m.end())
        i = m.end()
    return gaps


def _escaped(code, i):
    """Whether the character at i follows an odd run of backslashes."""
    return (i - len(code[:i].rstrip("\\"))) % 2 == 1


def _glued_before(code, start, op):
    """Whether the operator at start touches the word before it. Digits before `>` or `<` that start a word are its
    descriptor (`2>f`), so the operator is not glued to them; digits inside a word are the word's (`a2>f`), and so are
    digits after the `&` that ends a `>&` or `<&` (`2>&1>f`: the `>` is glued to `2>&1`)."""
    word = start if op[0] == "&" else len(code[:start].rstrip("0123456789"))
    if word < start and (word == 0 or code[word - 1] in _WORD_END and code[max(word - 2, 0):word] not in (">&", "<&")):
        return False
    return start > 0 and code[start - 1] not in _WORD_END


def _in_operator(code, i):
    """Whether the `&` or `|` at i in `code` belongs to a redirect operator."""
    prev = code[i - 1] if i else ""
    if code[i] == "|":
        return prev == ">"
    if code[i] != "&":
        return False
    return prev in ("<", ">") or (code[i + 1:i + 2] == ">" and prev != "&")
