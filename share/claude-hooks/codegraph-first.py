#!/usr/bin/env python3
"""PreToolUse hook on Bash: a search for a code symbol asks CodeGraph first.

CodeGraph (the codegraph CLI and its MCP server) is an optional integration: without it, leave this hook out.

Measured over two days on two teams: the same roles with the same instructions used CodeGraph for 80-83% of
their lookups on GPT models and 2-11% on Claude models, which used rg and grep instead. A text match is not a call
edge, and every match is followed by file reads; CodeGraph answers with the enclosing symbol, real callers and the
source. So when an agent's own command is rg or grep for something that looks like a code symbol, in code, this
hook stops it once with the CodeGraph command that answers the same question.

It is not a wall. rg stays the tool for prose, docs, config, logs and string literals, and those searches pass
untouched. After asking CodeGraph, an agent that still needs rg (a string, a generated file, something the index
cannot see) adds the marker `# codegraph-checked: <why>` at the end of the same command and it runs.

A hook, not an rg wrapper on PATH: it sees only the agent's own commands, so scripts and make recipes that call rg
are never affected. Any error inside it allows the call. Log: ~/.codegraph/codegraph-first.log (one line per stop
and per marker, for measuring)."""
import json, os, re, shlex, sys, time

MARK = "codegraph-checked"
SEARCH = {"rg", "grep", "egrep", "fgrep", "ggrep"}
NONCODE_EXT = (".md", ".txt", ".rst", ".toml", ".yaml", ".yml", ".json", ".jsonl", ".csv", ".log", ".out", ".ini",
               ".cfg", ".conf", ".plist", ".xml", ".html", ".lock", ".resolved", ".env", ".sql", ".diff", ".patch")
NONCODE_DIRS = ("docs", "doc", ".claude", "ledger", "scratchpad", "reports", ".git", "node_modules", "cargo-target",
                "target", ".build", "build", "dist", "fixtures", "golden")
NONCODE_TYPES = {"md", "markdown", "txt", "toml", "yaml", "json", "csv", "log", "config", "xml", "html"}
# rg options that take a value (so the next word is not the pattern or a path)
RG_VAL = {"-e", "--regexp", "-f", "--file", "-g", "--glob", "--iglob", "-t", "--type", "-T", "--type-not", "-m",
          "--max-count", "-A", "-B", "-C", "--after-context", "--before-context", "--context", "-M", "--max-columns",
          "--max-depth", "-d", "--maxdepth", "-j", "--threads", "-r", "--replace", "--sort", "--sortr", "--color",
          "--colors", "--encoding", "-E", "--type-add", "--pre", "--pre-glob", "--max-filesize", "--path-separator"}
GREP_VAL = {"-e", "-f", "-m", "-A", "-B", "-C", "--include", "--exclude", "--exclude-dir", "--max-count", "-d", "-D",
            "--color", "--label"}
# Roles without the CodeGraph tools (they run make and read logs): never stopped.
NO_CODEGRAPH = {"test-runner"}
LOG = os.path.expanduser("~/.codegraph/codegraph-first.log")
# Team folders live under $CODETEAM_WORKSPACE (default ~/codeteam-work); the hook acts only there.
TEAM_MARK = "/" + os.path.basename(os.path.normpath(os.environ.get("CODETEAM_WORKSPACE") or os.path.expanduser("~/codeteam-work"))) + "/team-"


DEFN = re.compile(r"^\^?\s*(pub(\(\w+\))?\s+)?(fn|func|def|struct|class|enum|protocol|trait|impl|extension|"
                  r"actor|typealias|type|let|var|const|static)\s+([A-Za-z_][A-Za-z0-9_]*)")


def symbolish(p):
    """True when the pattern names code symbols: one symbol, an alternation whose every branch is a symbol
    (`A|B|c_d`), or a definition search (`fn name`, `struct Name`, `func name`)."""
    p = p.strip()
    m = DEFN.match(p)
    if m:
        return True
    alts = [x for x in re.split(r"\\?\|", p) if x != ""]
    if len(alts) > 1:
        return all(one_symbol(x) for x in alts)
    return one_symbol(p)


def one_symbol(p):
    """A pattern that names a code symbol: CamelCase, snake_case, Type.member or a::path, or a whole-word
    identifier. Plain lowercase words, phrases and regex soup are prose or text, and pass."""
    core = re.sub(r"^(\\b|\\<|\^)|(\\b|\\>|\$)$", "", p.strip()).replace("\\b", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*((\.|::)[A-Za-z_][A-Za-z0-9_]*)*(\\?\()?", core):
        return False
    core = core.rstrip("(\\")
    if "::" in core or "." in core or "_" in core.strip("_"):
        return True
    return bool(re.search(r"[a-z][A-Z]|^[A-Z][a-z]+[A-Z]|^[A-Z][a-z0-9]{2,}$", core))


def code_target(paths, opts, globs=()):
    if any(o.startswith("--type=") and o.split("=", 1)[1] in NONCODE_TYPES for o in opts):
        return False
    globs = list(globs) + [o.split("=", 1)[1] for o in opts if o.startswith(("--glob=", "--iglob=", "--include="))]
    if globs and all(any(g.rstrip("'\"").endswith(e) for e in NONCODE_EXT) for g in globs):
        return False
    if not paths:
        return True
    for p in paths:
        q = p.rstrip("/")
        if q.endswith(NONCODE_EXT) or q in ("-",) or q.startswith(("/tmp", "/var", "/dev")):
            continue
        parts = [x for x in q.split("/") if x]
        if any(x in NONCODE_DIRS for x in parts) or "/.claude/projects" in os.path.expanduser(q):
            continue
        return True
    return False


def examine(words, piped):
    """None, or (pattern) when this segment is a code-symbol search by rg/grep."""
    cmd = os.path.basename(words[0])
    if cmd not in SEARCH:
        return None
    vals = RG_VAL if cmd == "rg" else GREP_VAL
    pattern, paths, opts, i, explicit = None, [], [], 1, False
    files_only = False
    globs = []
    while i < len(words):
        w = words[i]
        if w == "--":
            rest = words[i + 1:]
            if pattern is None and rest:
                pattern, rest = rest[0], rest[1:]
            paths += rest
            break
        if w.startswith("-") and len(w) > 1:
            opts.append(w)
            if w in ("--files", "-l", "--files-with-matches", "--files-without-match", "--count", "-c"):
                files_only = files_only or w == "--files"
            if w in ("-e", "--regexp") and i + 1 < len(words):
                pattern = words[i + 1]; explicit = True; i += 2; continue
            if w in vals and i + 1 < len(words):
                if w in ("-g", "--glob", "--iglob", "--include"):
                    globs.append(words[i + 1])
                elif w in ("-t", "--type"):
                    opts.append("--type=" + words[i + 1])
                i += 2; continue
            i += 1; continue
        if pattern is None:
            pattern = w
        else:
            paths.append(w)
        i += 1
    if files_only or pattern is None:
        return None
    if piped and not paths:
        return None   # filtering another command's output
    if not symbolish(pattern):
        return None
    if not code_target(paths, opts, globs):
        return None
    return pattern


def segments(cmd):
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=";&|()")
        lex.whitespace_split = True
        toks = list(lex)
    except ValueError:
        return []
    out, cur, piped, prev = [], [], False, None
    for t in toks:
        if t and set(t) <= set(";&|()"):
            if cur:
                out.append((cur, piped))
            piped = t == "|"
            cur = []
        else:
            cur.append(t)
    if cur:
        out.append((cur, piped))
    res = []
    for words, piped in out:
        while words and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0]):
            words = words[1:]
        while words and words[0] in ("command", "builtin", "time", "nice", "caffeinate", "-i", "env", "xargs"):
            words = words[1:]
        if words:
            res.append((words, piped))
    return res


def worktree_of(cwd, cmd):
    """The git root the agent is working in, for the suggested commands (a leading `cd <dir>` counts)."""
    import subprocess
    here = cwd
    m = re.match(r"\s*cd\s+(\"[^\"]+\"|'[^']+'|[^\s;&|]+)", cmd)
    if m:
        d = os.path.expanduser(m.group(1).strip("\"'"))
        here = d if os.path.isabs(d) else os.path.join(cwd, d)
    try:
        r = subprocess.run(["git", "-C", here, "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=3)
        return r.stdout.strip() or "<your worktree>"
    except Exception:
        return "<your worktree>"


def asked_codegraph(d):
    """How many CodeGraph calls (MCP tool or `codegraph` in Bash) the agent made in the tail of its own transcript,
    and the seconds since the last one. Subagents write to <session>/subagents/agent-<agent_id>.jsonl."""
    t = d.get("transcript_path") or ""
    if d.get("agent_id") and t:
        t = os.path.join(t[:-6] if t.endswith(".jsonl") else t, "subagents", f"agent-{d['agent_id']}.jsonl")
    try:
        with open(t, "rb") as fh:
            fh.seek(0, 2); n = fh.tell(); fh.seek(max(0, n - 1048576))
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return None, None
    count, last = 0, None
    for l in lines:
        if "codegraph" not in l or '"tool_use"' not in l:
            continue
        try:
            r = json.loads(l)
        except ValueError:
            continue
        for b in (r.get("message") or {}).get("content") or []:
            if not isinstance(b, dict) or b.get("type") != "tool_use":
                continue
            if b.get("name", "").startswith("mcp__codegraph") or (
                    b.get("name") == "Bash" and re.search(r"(^|[\s/;&|])codegraph\s", (b.get("input") or {}).get("command", ""))):
                count += 1; last = r.get("timestamp")
    ago = None
    if last:
        try:
            import datetime as _dt
            ago = int(time.time() - _dt.datetime.fromisoformat(last.replace("Z", "+00:00")).timestamp())
        except ValueError:
            pass
    return count, ago


def log(kind, d, pattern, extra=None):
    if os.environ.get("CODEGRAPH_FIRST_TEST"):
        return
    try:
        rec = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind, "agent": d.get("agent_type") or "session",
               "cwd": d.get("cwd"), "pattern": pattern}
        rec.update(extra or {})
        with open(LOG, "a") as fh:
            fh.write(json.dumps(rec) + "\n")
    except OSError:
        pass


def main():
    try:
        d = json.load(sys.stdin)
        if d.get("tool_name") != "Bash":
            return 0
        cmd = (d.get("tool_input") or {}).get("command", "")
        cwd = d.get("cwd") or os.getcwd()
        if TEAM_MARK not in os.path.realpath(cwd) and TEAM_MARK not in cmd:
            return 0
        if (d.get("agent_type") or "") in NO_CODEGRAPH:
            return 0
        if MARK in cmd:
            # What the marker let through, and whether CodeGraph was asked first (agents marked
            # 188 commands in the first hours and were stopped 59 times).
            pats = [x for x in (examine(w, p) for w, p in segments(re.sub(r"<<-?\s*'?(\w+)'?.*?\n\1\b", "", cmd, flags=re.S))) if x]
            n, ago = asked_codegraph(d)
            why = cmd.split(MARK, 1)[1].lstrip(":").strip()[:200]
            log("marked", d, pats[0] if pats else None, {"would_stop": bool(pats), "why": why, "codegraph_calls": n,
                                                          "last_codegraph_s_ago": ago, "command": cmd[:300]})
            return 0
        for words, piped in segments(re.sub(r"<<-?\s*'?(\w+)'?.*?\n\1\b", "", cmd, flags=re.S)):
            pat = examine(words, piped)
            if pat:
                log("stopped", d, pat)
                m = DEFN.match(pat.strip())
                name = m.group(4) if m else re.sub(r"\\b|\\<|\\>|\^|\$", "", pat).rstrip("(\\")
                if not m and len([x for x in re.split(r"\\?\|", name) if x]) > 1:
                    name = [x for x in re.split(r"\\?\|", name) if x][0]
                last = name.split("::")[-1].split(".")[-1]
                wt = worktree_of(cwd, cmd)
                print(f"CodeGraph first: `{os.path.basename(words[0])}` for `{pat}` is a text search for a code symbol. "
                      f"Ask CodeGraph, which answers with the enclosing symbol, real call edges and the source, so no "
                      f"file reads follow:\n"
                      f"  every occurrence, grouped by the symbol it sits in: codegraph grep '{name}' -p {wt}"
                      f"  (MCP: mcp__codegraph__codegraph_grep)\n"
                      f"  who calls it: codegraph callers {last} -p {wt}  (MCP: codegraph_callers)\n"
                      f"  its source, callers and callees: codegraph node {last} -p {wt}  (MCP: codegraph_node)\n"
                      f"If you have asked CodeGraph and still need this text search (a string, a generated file, something "
                      f"the index cannot see), run the same command with `# {MARK}: <why>` at the end. rg for docs, "
                      f"config, logs and prose needs no marker.", file=sys.stderr)
                return 2
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
