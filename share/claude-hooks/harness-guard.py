#!/usr/bin/env python3
"""PreToolUse (global): a team session never changes the harness.

The harness is what runs the teams, not any team's product: codeteam itself, the agent catalog, each team's role
files, Claude home and v2 state, Claude Code's own settings, and herdr's config. Teams were spending their time
"fixing" it, and one session changed the global model for everything. This hook refuses a write there from any
session codeteam started (CODETEAM_MANIFEST set), except team-codeteam's, whose product the harness is.
Reads are always fine. Sessions outside codeteam (the owner's own) are never touched.

Covers Edit, Write, MultiEdit and NotebookEdit by path, and Bash commands that name a harness path together with
something that writes (a redirect, tee, cp, mv, rm, ln, sed -i, git commit/add/push/checkout/reset...).
"""
import json
import os
import re
import sys
from pathlib import Path

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
                    r"sed\s+(-[a-zA-Z]*\s+)*-i|perl\s+-[a-z]*i|git\s+(-C\s+\S+\s+)?(commit|add|push|checkout|reset|"
                    r"restore|rm|mv|merge|rebase|stash|apply|am|cherry-pick|switch|branch|tag|worktree))(\s|$)")
PATHS = re.compile(r"""(?:^|[\s='"(>])((?:~|/)[^\s'";|&<>()]+)""")


TOOLS = {"codeteam", "codeteam2", "codeteam-land", "watch-agent", "zone-tool", "codeteam-slot", "codeteam-statusline",
         "make", "cd"}
SEPARATORS = {";", "&&", "||", "|", "&", "|&"}


def segments(cmd):
    """The parts of a compound command, split where the shell splits it: a separator inside quotes (a finding's
    --what text quoting code, such as `a > b; c | d`) stays in its part. Unbalanced
    quotes: split on every separator, as before."""
    import shlex
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=";&|")
        lex.whitespace_split = True
        lex.commenters = ""             # a mid-word '#' must not hide what follows
        tokens = list(lex)
    except ValueError:
        return [(seg, seg.split()) for seg in re.split(r"&&|\|\||;|\|", cmd)]
    out, words, raw = [], [], []
    for tok in tokens:
        if tok in SEPARATORS:
            out.append((" ".join(raw), words))
            words, raw = [], []
        else:
            words.append(tok)
            raw.append(shlex.quote(tok) if tok != tok.strip() or " " in tok else tok)
    out.append((" ".join(raw), words))
    return out


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
    tool = data.get("tool_name", "")
    inp = data.get("tool_input") or {}
    cwd = data.get("cwd") or os.getcwd()
    roots = harness_roots()
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        p = inp.get("file_path") or inp.get("notebook_path")
        if p and in_harness(resolve(p, cwd), roots):
            deny(f"{tool} of `{p}`")
        return
    if tool == "Bash":
        cmd = inp.get("command") or ""
        # Each part of a compound command on its own. A part that runs one of codeteam's own tools (say, watch,
        # push-up, watch-agent, zone-tool...) is how a team uses the harness, not a change to it: its arguments
        # (the manifest path, a message's words) are never read as writes.
        for seg, words in segments(cmd):
            while words and ("=" in words[0] and not words[0].startswith(("/", "~", "."))):
                words = words[1:]                                  # VAR=value prefixes
            if not words or os.path.basename(words[0]) in TOOLS:
                continue
            if not WRITES.search(seg):
                continue
            hits = [m.group(1) for m in PATHS.finditer(seg) if in_harness(resolve(m.group(1), cwd), roots)]
            if not hits and in_harness(resolve(cwd, cwd), roots):
                hits = [cwd]                     # a write run from inside the harness (git commit there)
            if hits:
                deny(f"a command that writes and names `{hits[0]}`")


if __name__ == "__main__":
    main()
