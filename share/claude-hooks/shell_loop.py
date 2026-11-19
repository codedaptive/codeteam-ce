"""has_loop: does a shell command hold a loop?

A loop is `for`, `while` or `until` used as a shell keyword: an unquoted, unescaped word in command position. A
command starts at the start, after a newline, `;`, `&`, `|`, `(`, `$(` or an opening backtick, and after a reserved
word that was itself in command position (`{`, `!`, `time`, `if`, `then`, `else`, `elif`, `do`, `while`, `until`).
The same word anywhere else is an argument, and a quoted or escaped one is never a keyword, as in the shell. A
`$(...)` or backtick substitution runs a command even inside double quotes, so its text is read as commands there too
(other-checkout Kong); single quotes hold no substitution. Comments and here-document bodies are not commands.
shell-loop-guard.py refuses a Bash call when this says yes."""
import re

LOOPS = {"for", "while", "until"}
OPENS = {"\n", ";", "&", "|", "(", "$(", "`"}                      # operators after which a command starts
RESERVED = {"{", "!", "time", "if", "then", "else", "elif", "do", "while", "until"}
# A here-document's body and end line; the line that opens it stays, since a pipeline can go on after `<<EOF`.
HEREDOC = re.compile(r"(<<-?[ \t]*(['\"]?)(\w+)\2[^\n]*\n).*?^[ \t]*\3[ \t]*$", re.S | re.M)


def _skip(s, i, close):
    """The index just past the quote or substitution that opened before i and ends with close ("'", '"', ")" or
    "`"), or len(s) when it never ends. What nests inside it (_opening) is skipped whole, so a close character in
    there is not this one's."""
    while i < len(s):
        c = s[i]
        if c == "\\" and close != "'":
            i += 2
        elif c == close:
            return i + 1
        elif inner := _opening(s, i, close):
            i = _skip(s, *inner)
        else:
            i += 1
    return len(s)


def _opening(s, i, close):
    """(where its text starts, the character that ends it) for what opens at s[i] and nests inside a quote or
    substitution ending with close, or None. Inside a double quote, $(...) and backticks nest; inside a $(...), so
    do both quotes and a bare ( (whose ) is its own, not the $(...)'s). Nothing nests inside single quotes or
    backticks."""
    c = s[i]
    if close not in '")':
        return None
    if c == "$" and s[i + 1:i + 2] == "(":
        return i + 2, ")"
    if c == "`" or (close == ")" and c in "'\"("):
        return i + 1, (")" if c == "(" else c)
    return None


def _substitutions(text):
    """The command text of each $(...) and backtick substitution at the top of a double-quoted string's text."""
    i = 0
    while i < len(text):
        if text[i] == "\\":
            i += 2
        elif text[i] == "$" and text[i + 1:i + 2] == "(":
            end = _skip(text, i + 2, ")")
            yield "$(", text[i + 2:end - 1]
            i = end
        elif text[i] == "`":
            end = _skip(text, i + 1, "`")
            yield "`", text[i + 1:end - 1]
            i = end
        else:
            i += 1


def _tokens(cmd):
    """(text, quoted) for each word, and (op, None) for each operator, in order; a substitution inside double quotes
    comes out as its opener, its own tokens and a closer, ahead of the word that holds it."""
    out, word, quoted, i, ticks = [], [], False, 0, False

    def end():
        nonlocal word, quoted
        if word:
            out.append(("".join(word), quoted))
        word, quoted = [], False

    while i < len(cmd):
        c = cmd[i]
        if c in " \t":
            end()
        elif c == "#" and not word:
            while i + 1 < len(cmd) and cmd[i + 1] != "\n":
                i += 1
        elif c in "'\"":
            inner, text, i = _quoted(cmd, i)
            out += inner
            word.append(text)
            quoted = True
        elif c == "\\":
            word.append(cmd[i + 1:i + 2])
            quoted, i = True, i + 1
        elif found := _operator(cmd, i, ticks):
            op, width = found
            end()
            out.append((op, None))
            ticks ^= op in ("`", "`end")          # a backtick opens a substitution or closes the open one
            i += width - 1
        else:
            word.append(c)
        i += 1
    end()
    return out


def _quoted(cmd, i):
    """For the quote that opens at cmd[i]: the tokens of each substitution a double quote holds (its opener, its own
    tokens and a closer), the quoted text, and the index of the closing quote."""
    close = _skip(cmd, i + 1, cmd[i])
    text = cmd[i + 1:close - 1]
    inner = []
    for opener, sub in (_substitutions(text) if cmd[i] == '"' else ()):
        inner += [(opener, None), *_tokens(sub), (")" if opener == "$(" else "`end", None)]
    return inner, text, close - 1


def _operator(cmd, i, ticks):
    """(op, its length) for the operator at cmd[i], or None: `$(`; a backtick, "`" when it opens a substitution and
    "`end" when ticks says one is open; or one of newline ; & | ( ) < >."""
    c = cmd[i]
    if c == "$" and cmd[i + 1:i + 2] == "(":
        return "$(", 2
    if c == "`":
        return ("`end" if ticks else "`"), 1
    if c in "\n;&|()<>":
        return c, 1
    return None


def has_loop(cmd):
    """True when cmd runs a for, while or until loop."""
    starts = True
    for text, quoted in _tokens(HEREDOC.sub(r"\1", (cmd or "").replace("\\\n", ""))):
        if quoted is None:
            starts = text in OPENS
        elif quoted is False and starts and text in LOOPS:
            return True
        else:
            starts = starts and quoted is False and text in RESERVED
    return False
