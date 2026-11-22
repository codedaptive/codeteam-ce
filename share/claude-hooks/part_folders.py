"""The folders each part of a compound shell command may run in, following its `cd`s; harness-guard.py uses it."""
import os
import sys

sys.dont_write_bytecode = True          # no __pycache__ beside the hooks in production's checkout
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from command_words import command_words
from redirects import redirects

_PIPES = {"|", "|&"}
_LIST_ENDS = {";", "&"}
_CONDITIONS = {"&&", "||"}
_WIDENS = {";", "||", "&"}
_EXTERNAL_WRAPPERS = {"env", "nohup", "nice", "exec", "timeout", "gtimeout"}


def part_folders(parts, cwd, home, resolve):
    """Each (seg, words, sep) of `parts`, `sep` the separator after the part, as (seg, words, folders): every folder
    it may run in, from `cwd`, deduplicated in first-seen order. A cd first or after `;` or `&` is taken to run and
    succeed, so it moves the parts after it, except:
    - a cd in a pipeline (`|` or `|&` before or after it) runs in a subshell and moves nothing;
    - after a part ending in `&` the folders go back to those where its and-or list (the parts since the last `;` or
      `&`) started, since bash runs that list in the background;
    - after `cd X ||`, the parts joined by `||`, `|` or `|&` (a pipeline binds tighter than `||`) up to the first part
      ending otherwise run only if the cd failed: they are judged in the folders before the cd, a cd among them moves
      nothing, and the parts after them run in X.
    A cd after `&&` or `||` may not run (D595): the parts joined to it by `&&`, `|` or `|&` run in its folders alone,
    and from the first `;`, `||` or `&` after it the folders before it are added back; a later such cd before then adds
    its folders to theirs. After a conditional `cd X ||` the failure parts are judged in the folders before it, those
    added back included; a cd among them not in a pipeline does not move the next one, but its folders, from theirs,
    are added to X's, where the parts after the chain run.
    A part is a cd when command_words' program is `cd`; the words it dropped before the cd decide what it does, the same
    in bash and zsh. Behind env, nohup, nice, exec, timeout or gtimeout it runs as a program and never moves the shell.
    Behind assignments alone, or assignments and the one word `builtin`, it moves the shell. Behind anything else
    (`command`, `time`, `!`, `noglob`, `nocorrect`, any option such as `builtin --` or `time -p`, more than one wrapper)
    it is uncertain: zsh runs `command cd` and `time -p cd` as the program cd, which moves nothing, where bash moves the
    shell, and `!` inverts its status. The parts after an uncertain cd run in the folders before it plus its folders,
    under every separator, and it never starts a `cd X ||` failure chain (in `! cd X || b`, b runs only if the cd
    succeeded).
    A cd's dirs are its words apart from options and redirects (`2>&1`, `> /dev/null`). Its folders: `home` with no
    dir; unchanged for `cd -` (OLDPWD is not tracked); else, for each folder the cd ran in, its last dir's logical
    folder, then its physical one, deduplicated. The logical folder is the dir joined to the folder and normalized with
    a leading `~` taken as `home` and no symlink resolved, so a later `cd ..` drops its last part as bash's `cd -L`
    does; the physical one is the caller's `resolve(path, cwd)`. With a symlink to elsewhere both are kept, and every
    later part is judged in each."""
    # held: the folders after a `cd X ||` chain while the parts that run only if the cd failed are judged;
    # wide: the folders the parts after a conditional cd widen to at the next `;`, `||` or `&`;
    # conditional: whether the cd that started the held chain came after `&&` or `||`
    folders, start, before, held, wide, conditional = (cwd,), (cwd,), ";", None, None, False
    for seg, words, sep in parts:
        if before in _LIST_ENDS:
            start = folders
        yield seg, words, folders
        piped = before in _PIPES or sep in _PIPES
        new, uncertain = (None, False) if piped else _cd_folder(words, folders, home, resolve)
        if held is not None:
            folders, held = _failure_step(folders, held, new, conditional, sep)
        elif new is not None:
            folders, held, wide, conditional = _cd_step(folders, wide, new, uncertain, before, sep)
        if wide and sep in _WIDENS:
            folders, wide = wide, None
        if sep == "&":
            folders = start
        before = sep


def _cd_step(folders, wide, new, uncertain, before, sep):
    """(folders, held, wide, conditional) after a cd that moves to `new`: a `cd X ||` that is not `uncertain` holds its
    folders for the parts after its failure chain; any other cd moves the next part, and a conditional one keeps the
    folders before it to widen back to."""
    conditional = before in _CONDITIONS
    carried = tuple(dict.fromkeys((wide or folders) + new)) if conditional else new
    if sep == "||" and not uncertain:
        return folders, carried, wide, conditional
    return new, None, carried, False


def _failure_step(folders, held, new, conditional, sep):
    """(folders, held) after a failure part of a `cd X ||` chain: in a `conditional` chain a cd's folders `new` join
    `held`; the chain goes on through `||`, `|` and `|&`, and the part after it runs in `held`."""
    if conditional and new is not None:
        held = tuple(dict.fromkeys(held + new))
    return (folders, held) if sep == "||" or sep in _PIPES else (held, None)


def _cd_folder(words, folders, home, resolve):
    """(new, uncertain) for a part: `new` the folders a `cd` goes to from each of `folders`, or None when the part is
    not a cd or its cd runs behind an external wrapper; an `uncertain` cd may not have moved the shell, so `new` is
    `folders` followed by its folders."""
    plain = redirects(words)[0]
    args = command_words(plain)
    wrappers = [w for w in plain[:len(plain) - len(args)] if not _is_assignment(w)]
    if not args or args[0] != "cd" or any(os.path.basename(w) in _EXTERNAL_WRAPPERS for w in wrappers):
        return None, False
    new = _cd_targets(args[1:], folders, home, resolve)
    if wrappers in ([], ["builtin"]):
        return new, False
    return tuple(dict.fromkeys(folders + new)), True


def _cd_targets(args, folders, home, resolve):
    """The folders a cd with `args` goes to from each of `folders`."""
    dirs = [a for a in args if a == "-" or not a.startswith("-")]
    if not dirs:
        return (home,)
    if dirs[-1] == "-":
        return folders
    return tuple(dict.fromkeys(p for f in folders for p in (_logical(dirs[-1], f, home), resolve(dirs[-1], f))))


def _logical(path, folder, home):
    """The folder `cd path` reaches from `folder` as bash tracks it: joined and normalized, `~` taken as `home`, no
    symlink resolved."""
    if path == "~" or path.startswith("~/"):
        path = home + path[1:]
    return os.path.normpath(os.path.join(folder, path))


def _is_assignment(word):
    """Whether `word` is a VAR=value assignment: it holds `=` and is not a path."""
    return "=" in word and not word.startswith(("/", "~", "."))
