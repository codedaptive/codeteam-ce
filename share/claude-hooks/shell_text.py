"""The code of a shell command line, apart from its text (D557): the provenance hook looks for the `git commit` the
shell runs, not one a heredoc writes into a file or a message quotes."""
import re

# `<<WORD`, `<<'WORD'`, `<<"WORD"` and `<<-WORD`; never the here-string `<<<`.
HEREDOC = re.compile(r"(?<!<)<<(?!<)(-?)[ \t]*(['\"]?)([A-Za-z_][\w.-]*)\2")
COMMENT_AFTER = " \t\n;&|("


def code_only(cmd: str) -> str:
    """cmd with the text of every quoted string, comment and here-document body replaced by "x" (newlines between
    lines of a body are kept), so a search finds only what the shell runs as code. The quotes, the heredoc operators
    and delimiter lines stay. The result has cmd's length, so a match's span in it is the same span in cmd. A string
    or body that is never closed runs to the end."""
    out, pending, i = list(cmd), [], 0
    while i < len(cmd):
        i = _step(cmd, out, i, pending)
    return "".join(out)


def _step(cmd, out, i, pending):
    """Reads the code at i, blanks any text that starts there, and returns where the next code starts."""
    c = cmd[i]
    if c in "'\"":
        return _blank_quoted(cmd, out, i)
    if c == "\\":
        return i + 2
    if c == "#" and _starts_word(cmd, i):
        end = cmd.find("\n", i)
        return _blank(out, i, len(cmd) if end < 0 else end)
    if c == "<" and (m := HEREDOC.match(cmd, i)):
        pending.append((m.group(1) == "-", m.group(3)))
        return m.end()
    if c == "\n" and pending:
        return _blank_bodies(cmd, out, i + 1, pending)
    return i + 1


def _starts_word(cmd, i):
    """A `#` here starts a comment: it begins the line or follows a blank or an operator (a mid-word `#` is text)."""
    return i == 0 or cmd[i - 1] in COMMENT_AFTER


def _blank_bodies(cmd, out, start, pending):
    """Blanks the bodies of the here-documents opened on the line that ends at start, in order; returns the index
    after the last one's delimiter line."""
    for dash, word in pending:
        start = _blank_body(cmd, out, start, dash, word)
    pending.clear()
    return start


def _blank(out, start, end):
    out[start:end] = "x" * (end - start)
    return end


def _blank_quoted(cmd, out, i):
    """Blanks the string opened by the quote at i (a backslash escapes inside double quotes only); returns the index
    after its closing quote."""
    quote, j = cmd[i], i + 1
    while j < len(cmd) and cmd[j] != quote:
        j += 2 if quote == '"' and cmd[j] == "\\" else 1
    j = min(j, len(cmd))
    _blank(out, i + 1, j)
    return j + 1


def _blank_body(cmd, out, start, dash, word):
    """Blanks the lines of one here-document body from start up to its delimiter line (tab-indented for `<<-`);
    returns the index after that line, or the end."""
    while start < len(cmd):
        end = cmd.find("\n", start)
        end = len(cmd) if end < 0 else end
        line = cmd[start:end]
        if (line.lstrip("\t") if dash else line) == word:
            return end + 1
        _blank(out, start, end)
        start = end + 1
    return len(cmd)
