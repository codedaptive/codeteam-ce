#!/usr/bin/env python3
"""PreToolUse (global): a team session never changes the harness.

The harness is what runs the teams, not any team's product: codeteam itself, the agent catalog, each team's role
files, Claude home and v2 state, Claude Code's own settings, and herdr's config. Teams were spending their time
"fixing" it, and one session changed the global model for everything. This hook refuses a write there from any
session codeteam started (CODETEAM_MANIFEST set), except team-codeteam's, whose product the harness is.
Reads are always fine. Sessions outside codeteam (the owner's own) are never touched.

Covers Edit, Write, MultiEdit and NotebookEdit by path, and Bash commands that write (a redirect, tee, cp, mv, rm, ln,
sed -i, git commit/add/push/checkout/reset...) and either name a harness path or run in a harness folder. A write runs
in its git command's `-C <dir>` when given, else in each folder part_folders follows the command's `cd`s to from the
session's cwd: a cd's logical folder (as bash tracks it, so `cd link && cd ..` is back where it started) and its
physical one, both judged (a piped cd moves none; parts joined by `&&` to one behind `&&` or `||` run in its folders
alone; part_folders has the rest, `&` and `cd X ||` included). A newline outside quotes and here-documents separates
commands as `;` does. Each part's redirect target is checked, codeteam's tools too.

Its helpers live beside this hook, one per file: segments.py (the command's parts; a redirect glued to a word is
split off, and the `&` or `|` of `2>&1` does not split), command_newlines.py (the newlines that end a command),
redirects.py (a part's words apart from its redirects, and the files those write), command_words.py, part_folders.py
and git_folder.py. A hyphenated hook can't be imported, so part_folders takes its HOME folder, and both part_folders
and git_folder take its cwd resolver, as arguments.
"""
import json
import os
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True          # no __pycache__ beside the hooks in production's checkout
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from command_words import command_words
from git_folder import git_folder
from part_folders import part_folders
from redirects import redirects
from segments import segments

HOME = Path.home()
MANIFEST = os.environ.get("CODETEAM_MANIFEST", "")
# The codeteam checkout: CODETEAM_HOME, else the repo this hook lives in (share/claude-hooks/ is two levels down).
CT_HOME = Path(os.environ.get("CODETEAM_HOME") or Path(__file__).resolve().parents[2])
# Where team folders live (CODETEAM_WORKSPACE, default ~/codeteam-work).
WORKSPACE = Path(os.environ.get("CODETEAM_WORKSPACE") or HOME / "codeteam-work")
# The agent catalog teams are built from (CODETEAM_CATALOG, default the checkout's catalog/).
CATALOG = Path(os.environ.get("CODETEAM_CATALOG") or CT_HOME / "catalog")


def team_root():
    """<workspace>/team-<product>, from the manifest's worktree_root, else from the session's folders."""
    try:
        import tomllib
        m = tomllib.loads(Path(MANIFEST).read_text())
        root = m.get("worktree_root")
        if root:
            return Path(os.path.expanduser(root)).resolve()
        return (WORKSPACE / f"team-{m.get('product', '')}").resolve()
    except Exception:
        return None


def harness_roots():
    roots = [CT_HOME, CATALOG,
             HOME / ".claude.json", HOME / ".claude" / "settings.json", HOME / ".claude" / "settings.local.json",
             HOME / ".claude" / "CLAUDE.md", HOME / ".claude" / "agents", HOME / ".claude" / "rules",
             HOME / ".claude" / "skills", HOME / ".claude" / "plugins", HOME / ".claude" / "hooks",
             HOME / ".config" / "herdr", HOME / ".local" / "bin"]
    tr = team_root()
    if tr:
        roots += [tr / "team" / "roles", tr / "team" / "claude", tr / "team" / "v2", tr / "team" / "launch",
                  tr / "team" / "HALTED", tr / "team" / "team.json"]
    out = []
    for r in roots:
        try:
            out.append(str(Path(r).resolve()))
        except OSError:
            out.append(str(r))
    return out


def resolve(p, cwd):
    p = os.path.expanduser(str(p))
    if not os.path.isabs(p):
        p = os.path.join(cwd or os.getcwd(), p)
    return os.path.realpath(os.path.normpath(p))


def in_harness(p, roots):
    return any(p == r or p.startswith(r + "/") for r in roots)


WRITES = re.compile(r"(^|[\s;&|(])(>>?|tee|cp|mv|rm|rmdir|ln|install|touch|mkdir|chmod|truncate|"
                    r"sed\s+(-[a-zA-Z]*\s+)*-i|perl\s+-[a-z]*i|git\s+(-C\s+\S+\s+)*(commit|add|push|checkout|reset|"
                    r"restore|rm|mv|merge|rebase|stash|apply|am|cherry-pick|switch|branch|tag|worktree))(\s|$)")
PATHS = re.compile(r"""(?:^|[\s='"(>])((?:~|/)[^\s'";|&<>()]+)""")


TOOLS = {"codeteam", "codeteam2", "codeteam-land", "watch-agent", "zone-tool", "codeteam-slot", "codeteam-statusline",
         "make", "cd"}


def deny(what):
    reason = (f"Refused: {what}. That is the harness (codeteam, the agent catalog, role files, Claude and herdr "
              f"settings), not your team's product. Don't change it, propose changes to it, or ask about it. If it "
              f"is wrong or missing, write one line in your status saying what, and carry on with the product. If it "
              f"truly blocks the product, say so in one line to your orchestrator; the owner fixes the harness.")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))
    sys.exit(0)


def main():
    if not MANIFEST or Path(MANIFEST).stem == "codeteam":
        return
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    what = refusal(data.get("tool_name", ""), data.get("tool_input") or {}, data.get("cwd") or os.getcwd(),
                   harness_roots())
    if what:
        deny(what)


def refusal(tool, inp, cwd, roots):
    """What a tool call would change in the harness, as the refusal names it, or None."""
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        p = inp.get("file_path") or inp.get("notebook_path")
        return f"{tool} of `{p}`" if p and in_harness(resolve(p, cwd), roots) else None
    if tool == "Bash":
        hit = next(filter(None, (part_target(seg, words, folder, roots) for seg, words, folders
                                 in part_folders(segments(inp.get("command") or ""), cwd, str(HOME), resolve)
                                 for folder in folders)), None)
        return f"a command that writes and names `{hit}`" if hit else None
    return None


def part_target(seg, words, folder, roots):
    """The harness path one part of a Bash command writes to, or None. Its redirects come first: each file a redirect
    writes is checked against `folder`, one folder the part may run in (the session's cwd, or one of a `cd` before it,
    as part_folders follows them), whatever the part runs. Then the part's other words: a part that runs one of
    codeteam's own tools (say, watch, push-up, watch-agent, zone-tool...) is how a team uses the harness, not a change
    to it, so its arguments (the manifest path, a message's words) are never read as writes, nor are those of a part
    WRITES does not match. The program a part runs is not what it writes either: `~/.local/bin/uv pip install --python
    <venv>/bin/python` writes into the venv. A write runs in `folder`, or a git `-C <dir>` in its
    place; an argument that names a harness path is refused (an absolute or `~` path, or a relative word that is not
    an option, resolved against where the write runs), and so is a write that runs inside the harness."""
    plain, targets = redirects(words)
    hit = next((t for t in targets if in_harness(resolve(t, folder), roots)), None)
    plain = command_words(plain)
    if hit or not plain or os.path.basename(plain[0]) in TOOLS or not WRITES.search(seg):
        return hit
    where = git_folder(plain, folder, resolve)
    named = [m.group(1) for m in PATHS.finditer(" ".join(plain[1:]))] + [where]   # the folder before plain words,
    named += (w for w in plain[1:] if not w.startswith("-"))                     # so a refusal names it
    return next((p for p in named if in_harness(resolve(p, where), roots)), None)


if __name__ == "__main__":
    main()
