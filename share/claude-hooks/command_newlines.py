"""The newlines of a shell command line that end a command, as `;` does; segments.py splits its parts there."""
import os
import sys

sys.dont_write_bytecode = True          # no __pycache__ beside the hooks in production's checkout
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shell_text import HEREDOC, code_only


def command_newlines(cmd: str) -> set[int]:
    """The indexes in `cmd` of the newlines that end a command: bash and zsh both run each line as its own command. A
    newline inside quotes, escaped by a backslash (a continuation), or in a here-document (the one that ends the line
    opening it, its body's, and none past its delimiter line) ends nothing. Nor does one with no command since the last
    newline that ended one, or after a separator (`a &&`, `a |`, `a;` go on to the next line), or with nothing but
    blanks after it, so no newline adds an empty part."""
    code = code_only(cmd)
    ends, last, start = set(), 0, 0
    while (nl := code.find("\n", start)) >= 0:
        ops = [(m.group(1) == "-", m.group(3))
               for m in HEREDOC.finditer(code, start, nl) if not _escaped(code, m.start())]
        if ops:
            start = _bodies_end(cmd, nl + 1, ops)
            continue
        if not _escaped(code, nl) and _ends_command(code, last, nl):
            ends.add(nl)
            last = nl
        start = nl + 1
    return ends


def _ends_command(code, last, nl):
    """Whether the newline at nl ends a command: a command since `last` that ends in no separator, and code after."""
    before = code[last:nl].strip()
    return bool(before) and before[-1] not in ";&|" and bool(code[nl + 1:].strip())


def _bodies_end(cmd, start, ops):
    """The index of the newline that ends the delimiter line of the last of the here-documents `ops` (dash, word),
    whose bodies follow one another from start, or the end of cmd."""
    end = start - 1
    for dash, word in ops:
        end = _delimiter_end(cmd, end + 1, dash, word)
    return end


def _delimiter_end(cmd, start, dash, word):
    """The index of the newline that ends the first line from start that is `word` (tab-indented for `<<-`), or the
    end of cmd."""
    while start < len(cmd):
        end = cmd.find("\n", start)
        end = len(cmd) if end < 0 else end
        if (cmd[start:end].lstrip("\t") if dash else cmd[start:end]) == word:
            return end
        start = end + 1
    return len(cmd)


def _escaped(code, i):
    """Whether the character at i follows an odd run of backslashes."""
    return (i - len(code[:i].rstrip("\\"))) % 2 == 1
