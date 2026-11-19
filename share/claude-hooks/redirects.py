"""The redirects among one part's words: what the part runs and the files it writes; harness-guard.py and
part_folders.py use it."""
import re
import sys

sys.dont_write_bytecode = True          # no __pycache__ beside the hooks in production's checkout

# A prefix (fd digits, or `&` for `&>`/`&>>`), the operator, then an operand glued on (possibly empty).
_REDIRECT = re.compile(r"(\d*|&)(>>|>\||>&|>|<<<|<<-|<<|<>|<&|<)(.*)")
_WRITES = {">", ">>", ">|", "<>"}
_FD = re.compile(r"\d+-?|-")            # `>&N`, `>&N-` and `>&-` move or close a descriptor; any other operand is a file


def redirects(words: list[str]) -> tuple[list[str], list[str]]:
    """(plain, targets): `plain` is every word that is not a redirect or a redirect's operand, in order; `targets` are
    the files the redirects write (`>`, `>>`, `>|`, `<>`, `&>`, `&>>`, and `>&` with a file operand, which bash reads
    as `&>`). An operator with nothing glued on takes the next word as its operand. Reads and descriptor moves (`<`,
    `<<`, `<<<`, `<&`, `>&N`, `>&-`) write nothing. A word holding whitespace is quoted text, never a redirect."""
    plain, targets, i = [], [], 0
    while i < len(words):
        m = None if any(c.isspace() for c in words[i]) else _REDIRECT.fullmatch(words[i])
        if not m:
            plain.append(words[i])
            i += 1
            continue
        prefix, op, operand = m.groups()
        if not operand and i + 1 < len(words):
            operand, i = words[i + 1], i + 1
        if operand and _writes(prefix, op, operand):
            targets.append(operand)
        i += 1
    return plain, targets


def _writes(prefix, op, operand):
    """Whether this redirect writes to the file its operand names."""
    if op == ">&":
        return not _FD.fullmatch(operand)
    return op in _WRITES and (prefix != "&" or op in (">", ">>"))
