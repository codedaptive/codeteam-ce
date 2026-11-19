"""The words of one part of a shell command from the program it runs on; harness-guard.py and part_folders.py use it."""
import os
import re
from functools import partial

_DURATION = re.compile(r"[0-9.]+[smhd]?")


def command_words(words):
    """One part's words from the program it runs on: its VAR=value prefixes dropped, then, as often as the first word
    (by basename) is a wrapper that runs another program unchanged (env, nohup, nice, time, command, builtin, exec,
    timeout, gtimeout, zsh's noglob and nocorrect, and `!`, which negates its status), that wrapper and its options. A
    wrapper option not in _WRAPPERS' table (builtin takes only `--`; noglob, nocorrect and `!` take none), `command -v`
    or `-V`, a timeout without a duration, or a wrapper left with nothing to run stops it: the words from that wrapper
    on are returned."""
    words = _after_assignments(words)
    while words and (skip := _WRAPPERS.get(os.path.basename(words[0]))):
        rest = skip(words[1:])
        if not rest:
            return words
        words = rest
    return words


def _after_assignments(words):
    """`words` from the first that is not a VAR=value assignment (a word with `=` that is not a path)."""
    start = next((i for i, w in enumerate(words) if "=" not in w or w.startswith(("/", "~", "."))), len(words))
    return words[start:]


def _after_options(args, flags=frozenset(), valued=frozenset(), joined=None):
    """`args` after a wrapper's leading options, or None at an option it does not take: `flags` stand alone (`--`
    among them ends the options), `valued` take the next word, and words `joined` matches carry their value."""
    i = 0
    while i < len(args) and args[i].startswith("-"):
        word = args[i]
        if word == "--" and word in flags:
            return args[i + 1:]
        if word in valued:
            i += 2
        elif word in flags or (joined and joined.fullmatch(word)):
            i += 1
        else:
            return None
    return args[i:]


def _env(args):
    """What env runs: its options, then its VAR=value words, dropped."""
    rest = _after_options(args, {"-i", "-", "-0", "-v", "--ignore-environment", "--"}, {"-u", "--unset"},
                          re.compile(r"-u.+|--unset=.+"))
    return None if rest is None else _after_assignments(rest)


def _timeout(args):
    """What timeout runs: its options and then exactly one duration dropped, or None without a valid duration."""
    rest = _after_options(args, {"--foreground", "--preserve-status", "-v", "--verbose"}, {"-s", "-k"},
                          re.compile(r"--signal=.+|--kill-after=.+"))
    return rest[1:] if rest and _DURATION.fullmatch(rest[0]) else None


_WRAPPERS = {
    "env": _env,
    "nohup": partial(_after_options, flags={"--"}),
    "nice": partial(_after_options, flags={"--"}, valued={"-n"}, joined=re.compile(r"-n-?\d+|-\d+|--adjustment=-?\d+")),
    "time": partial(_after_options, flags={"-p", "--"}),
    "command": partial(_after_options, flags={"-p", "--"}),
    "builtin": partial(_after_options, flags={"--"}),
    "noglob": _after_options,
    "nocorrect": _after_options,
    "!": _after_options,
    "exec": partial(_after_options, flags={"-c", "-l", "-cl", "-lc", "--"}, valued={"-a"}),
    "timeout": _timeout,
    "gtimeout": _timeout,
}
