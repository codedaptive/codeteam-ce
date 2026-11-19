"""The folder a git command writes in, from its `-C <dir>` options; harness-guard.py uses it."""
import os


def git_folder(words, folder, resolve):
    """The folder a git command writes in: each leading `-C <dir>` in turn, resolved against the one before it with
    the caller's `resolve(path, cwd)`. Any other command, or git without -C, runs in `folder`."""
    if not words or os.path.basename(words[0]) != "git":
        return folder
    i = 1
    while i + 1 < len(words) and words[i] == "-C":
        folder = resolve(words[i + 1], folder)
        i += 2
    return folder
