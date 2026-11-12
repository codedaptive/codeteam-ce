#!/usr/bin/env python3
"""Provenance trailers on every commit an agent makes (it must always happen, and the models must not be able
to skip it). Mechanical: no agent writes or sees any of it.

PostToolUse Edit|Write|MultiEdit|NotebookEdit  records who edited which file: the agent type, its model (from its
    agent file) and the effort level Claude Code reports, in <git dir>/codeteam-provenance.jsonl. Prints nothing.
PreToolUse Bash, on a `git commit`  rewrites the command to add, for each distinct (agent, model, effort) that
    edited files still uncommitted in that worktree, the trailers
        Agent: <agent type>   Model: <model>   Effort: <level>
    plus `Worktree: <branch>` (codeteam's accept carries these into the squash, beside Request:).
PostToolUse Bash, after a `git commit`  drops the records of files that are no longer uncommitted.
The model can't skip it: the trailers are added to the command by Claude Code before it runs, and
`--no-verify` does not affect `--trailer`."""
import json, os, re, shlex, subprocess, sys

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

def git(cwd, *a):
    r = subprocess.run(["git", "-C", cwd, *a], capture_output=True, text=True, timeout=10)
    return r.stdout.strip() if r.returncode == 0 else ""

def gitdir_of(path):
    d = path if os.path.isdir(path) else os.path.dirname(path) or "."
    while d and not os.path.isdir(d):
        d = os.path.dirname(d)
    return git(d, "rev-parse", "--absolute-git-dir"), git(d, "rev-parse", "--show-toplevel")

def agent_model(agent, project):
    if not agent:
        return os.environ.get("CODETEAM_MODEL", "")
    for base in (project, os.environ.get("CLAUDE_PROJECT_DIR", "")):
        p = os.path.join(base, ".claude", "agents", f"{agent}.md")
        if base and os.path.exists(p):
            m = re.search(r"^model:\s*(\S+)", open(p).read(), re.M)
            if m: return m.group(1)
    return ""

def transcript_model(d):
    """The model that actually answered, from the agent's own transcript: subagents write to
    <session>/subagents/agent-<agent_id>.jsonl beside the session transcript."""
    t = d.get("transcript_path") or ""
    if d.get("agent_id") and t:
        t = os.path.join(t[:-6] if t.endswith(".jsonl") else t, "subagents", f"agent-{d['agent_id']}.jsonl")
    try:
        with open(t, "rb") as fh:
            fh.seek(0, 2); n = fh.tell(); fh.seek(max(0, n - 262144))
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return ""
    # The latest API call's model (an `api-request` record, written before the tools run), else the latest reply's.
    for l in reversed(lines):
        if '"api-request"' not in l and '"assistant"' not in l: continue
        try: r = json.loads(l)
        except ValueError: continue
        if r.get("type") == "api-request":
            m = (r.get("params") or {}).get("model")
        elif r.get("type") == "assistant":
            m = (r.get("message") or {}).get("model")
        else:
            continue
        if m and m != "<synthetic>": return m
    return ""

def who(d, agent, project):
    return {"agent": agent or os.environ.get("CODETEAM_SESSION", "session"),
            "model": transcript_model(d) or agent_model(agent, project),
            "effort": (d.get("effort") or {}).get("level", "")}

def load(gd):
    p = os.path.join(gd, "codeteam-provenance.jsonl")
    out = []
    if os.path.exists(p):
        for l in open(p):
            try: out.append(json.loads(l))
            except ValueError: pass
    return p, out

def commit_dir(cmd, cwd):
    """The directory the commit runs in: `git -C <dir>`, else the last `cd <dir>` before it, else cwd."""
    g = re.search(r"\bgit\b(?:\s+(?:-C|-c)\s+\S+|\s+--?[\w-]+(?:=\S+)?)*\s+commit\b", cmd)
    pre = cmd[:g.start()] if g else cmd
    cds = re.findall(r"(?:^|[;&|(]\s*)cd\s+(\S+)", pre)
    if cds:
        cwd = os.path.join(cwd, os.path.expanduser(cds[-1].strip("'\"")))
    return _git_c_dir(cmd, cwd)

def _git_c_dir(cmd, cwd):
    m = re.search(r"\bgit\b(?:\s+(?:-c\s+\S+|--?[\w-]+(?:=\S+)?))*\s+-C\s+(\S+)(?:\s+(?:-c\s+\S+|--?[\w-]+(?:=\S+)?))*\s+commit\b", cmd)
    return os.path.join(cwd, os.path.expanduser(m.group(1).strip("'\""))) if m else cwd

def main():
    d = json.load(sys.stdin)
    if os.environ.get("CODETEAM_PROVENANCE_DEBUG"):
        open(os.environ["CODETEAM_PROVENANCE_DEBUG"], "a").write(json.dumps({k: v for k, v in d.items() if k not in ("tool_input", "tool_response")}) + "\n")
    ev, tool = d.get("hook_event_name"), d.get("tool_name")
    inp = d.get("tool_input") or {}; cwd = d.get("cwd") or os.getcwd()
    agent = d.get("agent_type") or ""
    if ev == "PostToolUse" and tool in EDIT_TOOLS:
        f = inp.get("file_path") or inp.get("notebook_path")
        if not f: return 0
        f = os.path.realpath(f if os.path.isabs(f) else os.path.join(cwd, f))
        gd, top = gitdir_of(f)
        if not gd: return 0
        rec = {"f": os.path.relpath(f, top), **who(d, agent, top)}
        with open(os.path.join(gd, "codeteam-provenance.jsonl"), "a") as fh:
            fh.write(json.dumps(rec) + "\n")
        return 0
    if tool != "Bash" or not re.search(r"\bgit\b[^;&|]*\bcommit\b", inp.get("command", "")):
        return 0
    cmd = inp["command"]; wd = commit_dir(cmd, cwd); gd, top = gitdir_of(wd)
    if not gd: return 0
    p, recs = load(gd)
    if ev == "PreToolUse":
        groups = []
        if not recs:  # edited by Bash (sed, scripts) or nothing recorded: the committer is the writer
            recs = [who(d, agent, top)]
        for r in recs:
            g = (r["agent"], r.get("model", ""), r.get("effort", ""))
            if g not in groups: groups.append(g)
        tr = []
        for a, m, e in groups:
            tr += ["--trailer", f"Agent: {a}", "--trailer", f"Model: {m or 'unknown'}", "--trailer", f"Effort: {e or 'unknown'}"]
        br = git(wd, "rev-parse", "--abbrev-ref", "HEAD")
        if br: tr += ["--trailer", f"Worktree: {br}"]
        add = " " + " ".join(shlex.quote(x) for x in tr)
        # the model may not write its own provenance
        cmd = re.sub(r"""\s--trailer[\s=]+(?:'(?:Agent|Model|Effort|Worktree)\s*[:=][^']*'|"(?:Agent|Model|Effort|Worktree)\s*[:=][^"]*"|(?:Agent|Model|Effort|Worktree)[:=]\S*)""", "", cmd, flags=re.I)
        new = re.sub(r"(\bgit\b(?:\s+(?:-C|-c)\s+\S+|\s+--?[\w-]+(?:=\S+)?)*\s+commit\b)", lambda m: m.group(1) + add, cmd, count=1)
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "updatedInput": {**inp, "command": new}}}))
        return 0
    if ev == "PostToolUse":
        dirty = {l[3:].strip().strip('"').split(" -> ")[-1] for l in git(wd, "status", "--porcelain").splitlines() if len(l) > 3}
        keep = [r for r in recs if r["f"] in dirty]
        with open(p, "w") as fh:
            fh.writelines(json.dumps(r) + "\n" for r in keep)
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)   # never block work over provenance
