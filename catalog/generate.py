"""Agent catalog v4: role files + small skills + a product layer -> one team's agents.

  python3 -I generate.py <product>                      build into build/<product>/ (agents, skills, rules)
  python3 -I generate.py <product> --install <team>     build, then point the team at it: link agents to the build,
                                                         copy skills and rules, record them in team/claude/catalog.json
                                                         (a first install archives the old folders; exit 1 on a conflict)
Layers: roles/<role>.md (kind, tools, base skills, body) / skills/ (shared) / products/<p>/product.toml (roles,
models, extra skills, on-demand skills) / products/<p>/skills/ / rules/global.md + products/<p>/rules/.
Sessions (kind session or both) get their skills built into the file: Claude Code does not preload skills: for a
session started with --agent (tested 2026-10-30). Subagents get skills: (preloaded, Skill tool or not).
Every agent that can start agents gets the 1-hour prompt cache; leaves (kind leaf) start without CLAUDE.md."""
import os, sys, re, shutil, tomllib, datetime, filecmp, subprocess, json as _json
HERE = os.path.dirname(os.path.abspath(__file__))
# Settings: CODETEAM_HOME (the codeteam checkout; default the folder above this catalog), CODETEAM_WORKSPACE (where
# team folders live; default ~/codeteam-work), CODETEAM_PYTHON (the interpreter hooks run with; default python3).
CODETEAM_HOME = os.environ.get("CODETEAM_HOME") or os.path.dirname(HERE)
WORKSPACE = os.environ.get("CODETEAM_WORKSPACE") or os.path.join(os.path.expanduser("~"), "codeteam-work")
MODEL = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5", "fable": "claude-fable-5-2"}
# Non-Claude models reach Claude Code through a model proxy you run yourself: model: gpt-6.1-sol(<effort>)[1m] plus
# effort: <effort> (both, so whichever the proxy honours agrees; [1m] so Claude Code assumes the 1M window).
# The shipped roster (rosters/claude.csv) uses Claude models only, so no proxy is needed.
PROXY = {"sol": "gpt-6.1-sol", "terra": "gpt-6.1-terra", "luna": "gpt-6-luna", "astra": "gpt-6-astra"}

# Rosters: rosters/<name>.csv (role,try,alias,type,persona,primary,fallback; primary like opus-5.5-medium).
# `claude` is the default; add your own roster file beside it and pick it with --roster:
#   python3 -I generate.py <product>|all [--roster claude|<yours>] [--install <team>]
# A product.toml [models] entry still wins for roles the roster does not carry (a product-specific role, math-expert on
# a product that sets it) or where a product needs an exception; the build log names every such override.
def load_roster(name):
    import csv
    out = {}
    for r in csv.DictReader(open(f"{HERE}/rosters/{name}.csv")):
        fam, _, eff = r["primary"].rpartition("-")          # opus-5.5-medium -> opus-5.5, medium
        fam = fam.split("-")[0]                              # opus-5.5 -> opus
        level = f"{fam}-{eff}"
        if r["try"]:
            out.setdefault(r["role"], []).append((int(r["try"]), level))
        else:
            out[r["role"]] = level
    for k, v in out.items():
        if isinstance(v, list): out[k] = [lv for _, lv in sorted(v)]
    # fold variants take their base role's model
    for base in list(out):
        out.setdefault(f"{base}-fold", out[base])
    return out
ROSTER_NAME = sys.argv[sys.argv.index("--roster") + 1] if "--roster" in sys.argv else "claude"
ROSTER = load_roster(ROSTER_NAME)

# Tools every role gets on top of its own: ToolSearch, so deferred MCP tools can load. Tool lists restrict, so a role
# that needs an MCP server's tools names them in products/<p>/product.toml [tools].
EVERY_ROLE_TOOLS = ["ToolSearch"]
def model_id(fam, effort):
    return MODEL[fam] if fam in MODEL else f"{PROXY[fam]}({effort})[1m]"

def front(path):
    t = open(path).read()
    m = re.match(r"---\n(.*?)\n---\n\n?(.*)", t, re.S)
    meta = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip()
    return meta, m.group(2)

def skill_path(product, name):
    for p in (f"{HERE}/products/{product}/skills/{name}/SKILL.md", f"{HERE}/skills/{name}/SKILL.md"):
        if os.path.exists(p): return p
    raise SystemExit(f"skill {name} not found for {product}")

def role_path(product, name):
    for p in (f"{HERE}/products/{product}/roles/{name}.md", f"{HERE}/roles/{name}.md"):
        if os.path.exists(p): return p
    raise SystemExit(f"role {name} not found for {product}")

def skill_body(product, name):
    return front(skill_path(product, name))[1].strip()

def build(product):
    cfg = tomllib.load(open(f"{HERE}/products/{product}/product.toml", "rb"))
    out = f"{HERE}/build/{product}"
    shutil.rmtree(out, ignore_errors=True); os.makedirs(f"{out}/agents")
    names = []
    for r in cfg["roles"]:
        meta, _ = front(role_path(product, r))
        n = int(meta.get("ladder", 0) or 0)
        names += [f"{r}-{i}" for i in range(1, n + 1)] if n else [r]
    used = set(cfg.get("on_demand", []))
    for r in cfg["roles"]:
        meta, body = front(role_path(product, r))
        kind = meta["kind"]
        skills = [s.strip() for s in meta["skills"].strip("[]").split(",") if s.strip()] + cfg.get("skills", {}).get(r, [])
        if r in cfg.get("models", {}) and r in ROSTER and cfg["models"][r] != ROSTER[r]:
            print(f"  {product}: {r} = {cfg['models'][r]} from product.toml overrides roster {ROSTER_NAME} ({ROSTER[r]})")
        models = cfg.get("models", {}).get(r) if r in cfg.get("models", {}) else ROSTER[r]
        n = int(meta.get("ladder", 0) or 0)
        levels = list(enumerate(models if isinstance(models, list) else [models], 1)) if n else [(0, models)]
        tools = meta["tools"]
        extra_agents = cfg.get("agents", {}).get(r, [])
        if extra_agents:   # product roles a generic role may start (e.g. a benchmark runner)
            tools = re.sub(r"Agent\(([^)]*)\)", lambda m: f"Agent({m.group(1)}, {', '.join(extra_agents)})", tools, count=1)
        def keep(m):
            kept = [x.strip() for x in m.group(1).split(",") if x.strip() in names]
            return f"Agent({', '.join(kept)})" if kept else ""
        tools = re.sub(r"Agent\(([^)]*)\)", keep, tools)
        tools = ", ".join(t for t in (x.strip() for x in tools.split(",")) if t)
        if cfg.get("tools", {}).get(r): tools += ", " + cfg["tools"][r]
        if "codegraph" in skills:   # the fleet's CodeGraph MCP server (codeteam mcp.json); tool lists restrict, so name them
            tools += ", " + ", ".join(f"mcp__codegraph__codegraph_{t}" for t in
                                      ("explore", "node", "search", "callers", "callees", "impact", "grep", "blast", "orphans", "suspects"))
        have = [x.strip() for x in tools.split(",")]
        tools += "".join(f", {t}" for t in EVERY_ROLE_TOOLS if t not in have)
        for i, level in levels:
            fam, effort = level.split("-")
            name = f"{r}-{i}" if i else r
            desc = meta["description"].replace("{N}", str(i))
            text = body.replace("{N}", str(i))
            fm = [f"name: {name}", f"description: >-\n  {desc}", f"tools: {tools}", f"model: {model_id(fam, effort)}", f"effort: {effort}"]
            if kind in ("session", "both"):
                # A session started with --agent does not preload skills:, but it can call them through the Skill
                # tool (tested 2026-11-01, Claude Code 2.1.307). Only skills marked load: always (the default) are
                # built in; load: demand skills are listed by name and read when needed: inlined skills were
                # 93-97% of every session's agent file.
                always = [s for s in skills if front(skill_path(product, s))[0].get("load", "always") != "demand"]
                demand = [s for s in skills if s not in always]
                if demand and "Skill" not in tools: tools += ", Skill"
                text = (text.rstrip() + "\n\n---\n\n<!-- Skills built in by generate.py (a session started with --agent does not preload skills:): "
                        + ", ".join(always) + ". Edit the skill files, not this. -->\n\n" + "\n\n".join(skill_body(product, s) for s in always) + "\n")
                if demand:
                    text += ("\n## Skills you load when you need them (Skill tool)\n\n" + "\n".join(
                        f"- `{s}`: {front(skill_path(product, s))[0]['description']}" for s in demand) + "\n")
            else:
                fm.append(f"skills: [{', '.join(skills)}]")
            fm[2] = f"tools: {tools}"          # sessions may have gained the Skill tool above
            if "Agent(" in tools: fm.append("experimental:\n  cacheTtl: 1h")
            if kind == "leaf": fm.append("omitClaudeMd: true")
            fm.append(f"generated: agent_catalog v4, product {product}, roster {ROSTER_NAME}, level {level} (edit roles/, skills/, rosters/ or products/{product}/, then run generate.py)")
            open(f"{out}/agents/{name}.md", "w").write("---\n" + "\n".join(fm) + "\n---\n\n" + text)
            used.update(skills)
    os.makedirs(f"{out}/skills"); os.makedirs(f"{out}/rules")
    for s in sorted(used):
        os.makedirs(f"{out}/skills/{s}"); shutil.copy(skill_path(product, s), f"{out}/skills/{s}/SKILL.md")
    g = open(f"{HERE}/rules/global.md").read()
    if product == "codeteam":   # the harness is this team's product: rule 9 does not apply
        g = re.sub(r"\n9\. \*\*The harness is not your work\.\*\*.*?(?=\n\d+\. |\Z)", "\n9. **The harness is your product** (team-codeteam only): `main` of the codeteam checkout is live for every team; see product.md.", g, flags=re.S)
    open(f"{out}/rules/global.md", "w").write(g)
    # crew.md: every agent knows the crew: who is who, what each does, what each hands back.
    rows = []
    for r in cfg["roles"]:
        meta, _ = front(role_path(product, r))
        n = int(meta.get("ladder", 0) or 0)
        agent = f"{r}-1..{n}" if n else r
        rows.append(f"| {meta.get('persona', '-')} | `{agent}` | {meta['kind']} | {meta.get('crew', meta['description']).replace('{N}', 'N')} |")
    open(f"{out}/rules/crew.md", "w").write(
        "# The crew\n\nWho is on this team and what each one does. A name in a message or a hand-back is one of these. "
        "Sessions are standing; subagents and leaves are started for one job and hand back once.\n\n"
        "| Name | Agent | Kind | Does |\n|---|---|---|---|\n" + "\n".join(rows) + "\n")
    # Effort ladders: only for the sessions the owner hands control to, keyed by role, model family and level;
    # codeteam's effort-mode hook reads them from team/claude/hooks/effort-ladders.json.
    import csv as _csv, json as _json
    lad = {}
    for row in _csv.DictReader(open(f"{HERE}/effort/ladders.csv")):
        if row["role"] in cfg["roles"]:
            lad.setdefault(row["role"], {}).setdefault(row["model"], {})[row["level"]] = {"mode": row["mode"], "text": row["text"]}
    os.makedirs(f"{out}/hooks", exist_ok=True)
    _json.dump(lad, open(f"{out}/hooks/effort-ladders.json", "w"), indent=1)
    for f in sorted(os.listdir(f"{HERE}/products/{product}/rules")):
        shutil.copy(f"{HERE}/products/{product}/rules/{f}", f"{out}/rules/{f}")
    return out, names, sorted(used)

# codeteam hooks every v4 team must have (provenance always happens). install() adds any that are missing to
# team/claude/settings.json, archiving the file first; entries already there are left alone.
HOOK_PY = (os.environ.get("CODETEAM_PYTHON") or "python3") + " " + os.path.join(CODETEAM_HOME, "share", "claude-hooks", "")
REQUIRED_HOOKS = [
    ("SessionStart", None, "effort-mode.py"), ("UserPromptSubmit", None, "effort-mode.py"), ("Stop", None, "effort-mode.py"),
    ("PreToolUse", "Bash", "provenance.py"),
    ("PostToolUse", "Edit|Write|MultiEdit|NotebookEdit|Bash", "provenance.py"),
    # An rg/grep for a code symbol asks CodeGraph first (Claude models used it for 2-11% of lookups); the hook lets
    # every command through when CodeGraph is not installed.
    ("PreToolUse", "Bash", "codegraph-first.py"),
]
# CodeGraph's worktree hook (optional; only when CodeGraph is installed): pins every codegraph MCP call to the git root
# of the calling agent's own cwd, so a subagent cannot query its parent's tree. It never blocks a call.
# CODETEAM_CODEGRAPH_HOOK overrides the command; by default it is added only when the npm package is found.
_CG_MAIN = "/opt/homebrew/lib/node_modules/@colbymchenry/codegraph/dist/extensions/host/worktree-hook/main.js"
CODEGRAPH_HOOK = os.environ.get("CODETEAM_CODEGRAPH_HOOK") or (f"node {_CG_MAIN}" if os.path.exists(_CG_MAIN) else "")
REQUIRED_COMMAND_HOOKS = [("PreToolUse", "mcp__codegraph__.*", "worktree-hook/main.js", CODEGRAPH_HOOK)] if CODEGRAPH_HOOK else []

def ensure_hooks(c):
    p = f"{c}/settings.json"
    d = _json.load(open(p)) if os.path.exists(p) else {}
    h = d.setdefault("hooks", {}); added = []
    for ev, matcher, script in REQUIRED_HOOKS:
        groups = h.setdefault(ev, [])
        if any(script in x.get("command", "") and g.get("matcher") == matcher for g in groups for x in g.get("hooks", [])):
            continue
        g = {"hooks": [{"type": "command", "command": HOOK_PY + script, "timeout": 10}]}
        if matcher: g = {"matcher": matcher, **g}
        groups.append(g); added.append(f"{ev}:{script}")
    for ev, matcher, key, command in REQUIRED_COMMAND_HOOKS:
        groups = h.setdefault(ev, [])
        if any(key in x.get("command", "") and g.get("matcher") == matcher for g in groups for x in g.get("hooks", [])):
            continue
        groups.append({"matcher": matcher, "hooks": [{"type": "command", "command": command, "timeout": 10}]})
        added.append(f"{ev}:{key}")
    if added:
        if os.path.exists(p):
            arch = os.path.join(os.path.dirname(c), "claude-archive"); os.makedirs(arch, exist_ok=True)
            shutil.copy(p, os.path.join(arch, f"settings.json.before-hooks-{datetime.datetime.now().strftime('%Y-%m-%dT%H%M%S')}"))
        with open(p, "w") as fh:
            _json.dump(d, fh, indent=2); fh.write("\n")
    return added

FOLDERS = ("agents", "skills", "rules")

def remove(p):
    if os.path.isdir(p) and not os.path.islink(p): shutil.rmtree(p)
    elif os.path.lexists(p): os.unlink(p)

def place(out, c, d, f):
    # Built under a temp name in the same folder, then renamed: a name exists only complete. A leftover temp of the
    # same name from a cut-off install is ours and is removed first.
    p, tmp, src = f"{c}/{d}/{f}", f"{c}/{d}/.{f}.installing", f"{out}/{d}/{f}"
    remove(tmp)
    if os.path.isdir(p) and not os.path.islink(p) and d != "skills": remove(p)   # os.replace cannot overwrite a dir
    if d == "agents": os.symlink(src, tmp); os.replace(tmp, p)
    elif d == "rules": shutil.copy(src, tmp); os.replace(tmp, p)
    else: shutil.copytree(src, tmp); remove(p); os.rename(tmp, p)

def tree_files(root):
    return sorted(os.path.relpath(os.path.join(r, n), root) for r, _, ns in os.walk(root) for n in ns)

def equals_build(out, c, d, f):
    """True when the entry already on disk is what place() would make: the same link, or the same bytes."""
    p, b = f"{c}/{d}/{f}", f"{out}/{d}/{f}"
    if d == "agents": return os.path.islink(p) and os.readlink(p) == b
    if os.path.islink(p): return False
    if d == "rules": return os.path.isfile(p) and filecmp.cmp(p, b, shallow=False)
    names = tree_files(b)
    return os.path.isdir(p) and tree_files(p) == names and all(filecmp.cmp(f"{p}/{n}", f"{b}/{n}", shallow=False) for n in names)

def archive_old(c):
    """Moves the existing agents/skills/rules into the first claude-archive/before-v4-<date>[-N] that holds none of
    them; returns that dir, or None when there was nothing to move."""
    moving = [d for d in FOLDERS if os.path.lexists(f"{c}/{d}")]
    if not moving: return None
    base = os.path.join(os.path.dirname(c), "claude-archive", f"before-v4-{datetime.date.today().isoformat()}")
    n, dest = 1, base
    while any(os.path.lexists(f"{dest}/{d}") for d in moving): n += 1; dest = f"{base}-{n}"
    os.makedirs(dest, exist_ok=True)
    for d in moving: shutil.move(f"{c}/{d}", f"{dest}/{d}")
    return dest

def sync_folder(out, c, d, old):
    """Brings c/<d> to the build, touching only names on the record (old) or in the build. Returns (report, placed names)."""
    os.makedirs(f"{c}/{d}", exist_ok=True)
    new, old = set(os.listdir(f"{out}/{d}")), set(old)
    r = {"replaced": 0, "removed": 0, "created": 0, "left_alone": 0, "conflicts": []}
    placed = []
    for f in sorted(old | new):
        p = f"{c}/{d}/{f}"
        if f not in new:
            r["removed"] += os.path.lexists(p); remove(p)
            continue
        if f in old: r["replaced"] += 1; place(out, c, d, f)
        elif not os.path.lexists(p): r["created"] += 1; place(out, c, d, f)
        elif equals_build(out, c, d, f): r["replaced"] += 1   # an earlier install was interrupted after placing it: adopt
        else: r["conflicts"].append(f); continue
        placed.append(f)
    r["left_alone"] = len(set(os.listdir(f"{c}/{d}")) - old - new)
    return r, placed

def catalog_commit():
    try: return subprocess.run(["git", "-C", HERE, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError): return None

def write_record(c, record):
    # temp file in c, fsynced, then os.replace: the record is the old one or the new one, never half of either
    tmp = f"{c}/catalog.json.tmp"
    with open(tmp, "w") as fh:
        _json.dump(record, fh, indent=2); fh.write("\n")
        fh.flush(); os.fsync(fh.fileno())
    os.replace(tmp, f"{c}/catalog.json")

def install(product, out, team):
    """Points the team at the build. team/claude/catalog.json lists what the last install placed: a name on it is
    replaced or removed, a name off it is never touched (a build name on disk but off it is a conflict, kept and
    reported, unless it already equals the build: then it is adopted onto the record). No record means a first
    install: the old folders go to claude-archive beside the claude home, never inside it, which holds only what
    sessions read. The record is written last: an install interrupted before it leaves the old record, and rerunning
    the same build converges. Returns (claude home, archive dir or None, report per folder)."""
    c = os.path.join(os.path.expanduser(team), "team", "claude")
    rec = f"{c}/catalog.json"
    old = None
    if os.path.exists(rec):
        with open(rec) as fh: old = _json.load(fh)["files"]
    arch = archive_old(c) if old is None else None
    report, files = {}, {}
    for d in FOLDERS:
        report[d], files[d] = sync_folder(out, c, d, (old or {}).get(d, []))
        r = report[d]
        print(f"  {d}: replaced {r['replaced']}, removed {r['removed']}, created {r['created']}, left alone {r['left_alone']}, conflicts {len(r['conflicts'])}")
        for f in r["conflicts"]: print(f"    {c}/{d}/{f} is not on the record: kept, not installed")
    os.makedirs(f"{c}/hooks", exist_ok=True); shutil.copy(f"{out}/hooks/effort-ladders.json", f"{c}/hooks/effort-ladders.json")
    added = ensure_hooks(c)
    if added: print(f"  hooks added to {c}/settings.json: {', '.join(added)}")
    write_record(c, {"product": product, "catalog_commit": catalog_commit(),
                     "installed_at": datetime.datetime.now().isoformat(timespec="seconds"), "files": files})
    return c, arch, report

if __name__ == "__main__":
    # `all --install` rebuilds every product and reinstalls each into $CODETEAM_WORKSPACE/team-<product> (skills and rules are
    # copies, so a skill change needs a reinstall everywhere it is used). Exit 1 when any install kept a conflict.
    products = sorted(os.listdir(f"{HERE}/products")) if sys.argv[1] == "all" else [sys.argv[1]]
    conflicted = False
    for product in products:
        out, names, used = build(product)
        print(f"{product}: {len(names)} agents, {len(used)} skills -> {out}")
        if "--install" in sys.argv:
            team = sys.argv[sys.argv.index("--install") + 1] if sys.argv[1] != "all" else os.path.join(WORKSPACE, f"team-{product}")
            c, arch, report = install(product, out, team)
            conflicted |= any(r["conflicts"] for r in report.values())
            print(f"  installed into {c}")
            if arch is not None: print(f"  previous agents/skills/rules in {arch}")
    if conflicted: sys.exit(1)
