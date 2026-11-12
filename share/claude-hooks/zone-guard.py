#!/usr/bin/env python3
"""codeteam zone guard (2026-10-23, the user's ruling): a lane session, and every
agent it starts, works in its own zone and nowhere else. The whole repo is in the
lane's worktree only so its zone can build; nothing outside the zone is the lane's
to edit, build alone, test or run.

Acts for a lane session only (CODETEAM_SWT and CODETEAM_SESSION set), so Orc, the
assistants and other teams pass straight through. A lane on a zone (not ".") gets
everything below. A whole-repo lane (zone ".") with other lanes' folders to respect
(a walled lane) may run and build anything; its edits and shell writes are walled, it
gets the git checks (the scratch-clone refusal, the paths of git add, rm and mv),
the compaction and note hooks and the subagent rule. A whole-repo lane with no walls
gets the compaction and note hooks, and its writes (edits and shell writes) in its own
worktrees to the paths the team manifest's orchestrator_owns names are refused, as are
git add, rm and mv on them; no other git check (git restore, checkout, commit, push and the
rest are not checked), no make, test or build check, no subagent rule. One script, one mode per hook
event (argv[1]):

  pretool   PreToolUse on Edit|Write|MultiEdit|NotebookEdit|Bash. Refuses an edit,
            a shell write, a make target, a test or a build outside the zone
            (exit 2; the reason goes back to the agent). A walled lane is not
            refused the make, test or build; for an unwalled whole-repo lane only a
            write to an orchestrator_owns path is refused (an edit, a shell write, git
            add, rm or mv); its other git commands are not checked.
  context   PostToolUse. At 70% of the context window, tells the session to write
            its handoff (/prepare-for-compact) and posts the same as a message.
  stop      Stop. After the handoff ("Ready. Run /compact now."), has codeteam run
            /compact and then the resume line. After a push or a closed request
            with no note filed, sends the session back to file it, once (only when
            CODETEAM_NOTE_TOOLS names the tools that file a note). A push is a
            command that runs one (runs_push), not text that names it.
  start     SessionStart (startup, resume, compact). The zone brief.
  subagent  SubagentStart. The zone rule for every agent the lane starts.

Which paths a lane may edit (its zone, `owns`, other lanes' areas, the manifest's
orchestrator_owns, reference docs in docs/reference, docs/_public/reference and
docs/internal/reference, lockfiles) is decided by lane_walls.py, which `codeteam push-up` shares;
the guard keeps the rest (shell, make, git, worktree housekeeping).

Fails open on its own errors (logged): a bug here must not stop the team.
Hooks cost no tokens; only the text they add to a context does.
"""
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

from lane_walls import OWNED_DOC_DIRS, load_walls, refused_by   # the ownership rule, shared with push-up

HOME = Path.home()
ZONE = os.environ.get("CODETEAM_ZONE", "").strip().strip("/")
SWT = os.environ.get("CODETEAM_SWT", "")
LANE = os.environ.get("CODETEAM_SESSION", "")
# The codeteam checkout: CODETEAM_HOME, else the repo this hook lives in (share/claude-hooks/ is two levels down).
CT_HOME = Path(os.environ.get("CODETEAM_HOME") or Path(__file__).resolve().parents[2])
# Where team folders live (CODETEAM_WORKSPACE, default ~/codeteam-work).
WORKSPACE = Path(os.environ.get("CODETEAM_WORKSPACE") or HOME / "codeteam-work")
# The codeteam command hooks call (say, compact-now): v1, or codeteam2 for a team on herdr (2026-10-24).
CT_BIN = os.environ.get("CODETEAM_BIN") or str(CT_HOME / "bin" / "codeteam")
LOG = HOME / ".claude" / "audit" / "hook-events.log"
LANE_DIR = Path(SWT).parent if SWT else None
TEAM_ROOT = LANE_DIR.parent.parent if LANE_DIR else None
# The guard applies inside the team workspace and the codeteam checkout; paths elsewhere are free.
PROTECTED = [str(WORKSPACE), str(CT_HOME)]
PREPARE_AT = float(os.environ.get("CT_CTX_PREPARE", "0.70"))
# More paths the lane owns besides its zone folder (the manifest's `owns`; globs allowed).
OWNS = [x.strip().strip("/") for x in os.environ.get("CODETEAM_OWNS", "").split(":") if x.strip()]
PRODUCT = TEAM_ROOT.name.removeprefix("team-") if TEAM_ROOT else "team"
ORC = f"Orc-{PRODUCT[:1].upper()}{PRODUCT[1:]}"
# MCP tool names (substrings, comma-separated) that count as filing a note after a push; empty: no note check.
NOTE_TOOLS = [x.strip() for x in os.environ.get("CODETEAM_NOTE_TOOLS", "").split(",") if x.strip()]

# Unconditionally listed lane targets at the repo root; scoped targets and the
# zone's configured targets are checked separately before other targets are refused.
LANE_TARGETS = {"help", "zone-test", "zone-test-one", "zone-test-status", "warm",
                "test-one", "test-one-no-features", "test-repeat", "build-one",
                "public-docs", "check-public-docs", "pg-status", "list", "clippy-one",
                "test-shape", "test-times", "pg-up", "pg-down"}
# These targets require the named variable; DIR is also checked against the zone.
# zone-tool check defaults DIR to "." and passes it through the environment;
# a check command may ignore DIR, so naming a path does not guarantee its scope.
SCOPED_TARGETS = {"check-windows": "WINDOWS_PKGS", "zone-check": "DIR"}


def zone_targets():
    try:
        return set(json.loads((CT_HOME / "zone" / "zone-targets.json").read_text()).get(ZONE, []))
    except (OSError, ValueError):
        return set()


LOCKED_VARS = {"ZONE_TEST", "ZONE_ROOT", "ZONE_TOOL"}   # would let a zone target run anything
MAKE_PRINT_ONLY = {"-n", "--dry-run", "--just-print", "--recon", "-q", "--question"}
MAKE_ARG_OPTIONS = {"-f", "--file", "--makefile", "-o", "-W", "-I", "--include-dir"}
MAKE_VAR_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\+?[:?]?=(.*)$")
WRAPPERS = {"env", "nice", "time", "timeout", "gtimeout", "nohup", "caffeinate", "command",
            "exec", "stdbuf", "chronic", "unbuffer"}
SEPARATORS = {";", "&&", "||", "|", "&", "|&", ";;", "(", ")", "{", "}", "!", ";&", "&;"}


def active():
    """A zone lane: the fence, the zone brief and the subagent rule apply."""
    return bool(ZONE) and ZONE != "." and bool(SWT) and bool(LANE)


def walls():
    """A whole-repo lane (zone ".") on a team where other lanes own folders (say, a
    benchmarking lane beside a harness lane): it may run and build anything, and edits anything but
    another lane's folders. A path that matches another lane's folder
    only in case (`V2/x` for `v2`) is refused too."""
    return ZONE == "." and lane_session() and lane_rule().walled()


def orc_only():
    """An unwalled whole-repo lane (zone ".") on a team whose manifest sets orchestrator_owns:
    it is refused only writes to those paths: edits, shell writes and git add, rm
    and mv. git restore, checkout, commit, push and other git subcommands are not checked, and
    no zone fence, test route, make or build check applies to it."""
    return ZONE == "." and lane_session() and not lane_rule().walled() and bool(lane_rule().orchestrator_owns)


_WALLS = None


def lane_rule():
    """The lane's ownership facts (lane_walls.Walls), built on first use, never at import."""
    global _WALLS
    if _WALLS is None:
        _WALLS = load_walls(lane=LANE, zone=ZONE, owns=OWNS,
                            team_json=TEAM_ROOT / "team" / "team.json" if TEAM_ROOT else None,
                            codeteam_home=CT_HOME, manifest=manifest())
    return _WALLS


def lane_session():
    """Any codeteam lane, a whole-repo one too (say, a data or training lane):
    the compaction and note hooks apply."""
    return bool(SWT) and bool(LANE)


def log(result, why=""):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with LOG.open("a") as f:
            f.write(f"{ts} | zone-guard | lane={LANE} | zone={ZONE} | result={result} | {why[:300]}\n")
    except OSError:
        pass


# The zoned notices name the documentation exception so agents know they may edit
# their zone's own SPEC and INTERFACE. lane_walls.owns_doc enforces the exception;
# rule_text omits it from the whole-repo walls notice. tests/zone-guard.sh and
# zone/tests/zone-guard-doc-exception.sh pin this phrase: a change to it is a change to both.
DOC_EXCEPTION = (", plus your zone's own SPEC and INTERFACE in `docs/reference` or "
                 "`docs/internal/reference` and their `docs/_public` copies")


def rule_text():
    if walls():
        return (f"You work for the {LANE} lane. You may run and build anything in the repo, but these "
                "belong to other lanes and you never edit them: "
                + ", ".join(f"`{x}` ({n})" for n, x in other_owned()) +
                f". A change one of them needs goes to {ORC} as a NOTE naming the file and what it needs; "
                "the lane that owns it makes it. A guard refuses edits there.")
    own = ", ".join(f"`{x}`" for x in [ZONE, *OWNS])
    return (f"You work for the {LANE} lane, in zone {own}, and nowhere else. Edit, build and test "
            "only what is there" + DOC_EXCEPTION + ". When other code needs a change, say so in your report (the lane sends "
            f"{ORC} a NOTE naming the file and what it needs): its own lane does that work. "
            "A guard refuses edits, builds and tests outside the zone.")


class Denied(Exception):
    pass


# ---------------------------------------------------------------- one test route
# Tests run once, through `make zone-test-one`, whose record answers a repeat until something the tests can touch
# changes. Every other way to run them (cargo test, swift test, xcodebuild test, make test-one, the runner's own
# scripts) has no record and no cache, and was how sessions re-ran passing tests "to be sure". The whole zone suite
# (`make zone-test`) is the coordinator's: a subagent (a lead, coder, writer, reviewer) never runs it.
TEST_ROUTE = "TEST:"
AGENT_ID = ""
DIRECT_TEST_MAKE = {"test-one", "test-one-no-features", "test-repeat"}
TEST_HELPERS = ("swift-test-xcode",)


def check_test_route(words):
    cmd = os.path.basename(words[0])
    args = words[1:]
    sub = next((w for w in args if not w.startswith("-") and not w.startswith("+")), "")
    why = ""
    if cmd == "cargo" and sub in ("test", "nextest", "bench"):
        why = f"`cargo {sub}`"
    elif cmd == "swift" and sub == "test":
        why = "`swift test`"
    elif cmd == "xcodebuild" and any(a in ("test", "test-without-building") for a in args):
        why = "`xcodebuild test`"
    elif cmd in ("make", "gmake"):
        if any(a in ("-n", "--dry-run", "--just-print", "--recon", "-q", "--question") for a in args):
            return
        targets = [a for a in args if not a.startswith("-") and "=" not in a]
        direct = [t for t in targets if t in DIRECT_TEST_MAKE]
        if direct:
            why = f"`make {direct[0]}`"
        elif "zone-test" in targets and AGENT_ID:
            raise Denied(TEST_ROUTE + "`make zone-test` (the whole zone suite) is the coordinator's; a subagent "
                         "runs only the tests its brief names, with `make zone-test-one`")
    elif cmd in TEST_HELPERS or (
            cmd.startswith("python") and any(os.path.basename(a) in TEST_HELPERS for a in args)):
        why = f"`{next((os.path.basename(w) for w in words if os.path.basename(w) in TEST_HELPERS), cmd)}`"
    if why:
        raise Denied(TEST_ROUTE + f"{why} runs tests with no record and no cache; run them with "
                     "`make zone-test-one DIR=<package> [SWIFT_TEST_ARGS=...|CARGO_TEST_ARGS=...]`, which answers "
                     "from the record when nothing the tests touch has changed")


def deny(what):
    raise Denied(what)


# ---------------------------------------------------------------- paths

def resolve(p, cwd):
    p = os.path.expanduser(str(p))
    if not os.path.isabs(p):
        p = os.path.join(cwd, p)
    return os.path.realpath(os.path.normpath(p))


def protected(p):
    return any(p == r or p.startswith(r + "/") for r in PROTECTED)


def worktree_root(p):
    """The nearest folder at or above p with a .git entry, stopping before LANE_DIR or
    TEAM_ROOT if encountered; otherwise recognize a standing, request, work-order or
    .claude/worktrees tree by position, even if absent, or return None. SWT must be the
    standing workcrews/<lane>/<swt> worktree, including for a subagent in a work-order
    tree, so TEAM_ROOT is the team folder."""
    cur = Path(p)
    for a in [cur, *cur.parents]:
        if LANE_DIR and str(a) in (str(LANE_DIR), str(TEAM_ROOT)):
            break
        if (a / ".git").exists():
            return a
    if LANE_DIR:
        m = re.match(re.escape(str(LANE_DIR)) + r"/(requests/[^/]+|" + re.escape(Path(SWT).name) + r")(/|$)", str(p))
        if m:
            return LANE_DIR / m.group(1)
        m = re.match(r"(" + re.escape(str(TEAM_ROOT)) + r"/wo/" + re.escape(LANE) + r"/[^/]+)(/|$)", str(p)) if LANE else None
        if m:
            return Path(m.group(1))
    m = re.match(r"(.*/\.claude/worktrees/[^/]+)(/|$)", str(p))
    return Path(m.group(1)) if m else None


def other_owned():
    """[(lane, path or glob)] that other lanes own: their zone folder and their `owns`."""
    return lane_rule().others()


def owns_doc(rel):
    """True for <ZONE>_*.md in docs/reference, docs/_public/reference or docs/internal/reference
    (the rule is lane_walls')."""
    return lane_rule().owns_doc(rel)


def untracked_root_file(p):
    """A file of the lane's own at a worktree's top (status.md, notes) that git does not track,
    even with case ignored: on APFS `PACKAGES/x` is the tracked `packages/x`, so a case variant
    of a tracked top entry is never the lane's own (case is never folded to let a
    path through). `:(icase,literal)` matches case-blind and takes the name as is (no glob)."""
    wt = worktree_root(p)
    if wt is None or not (wt / ".git").exists():
        return False
    top = os.path.relpath(p, wt).split(os.sep)[0]
    env = dict(os.environ, GIT_CEILING_DIRECTORIES=str(wt.parent))   # this worktree's git, never a parent's
    # Any of these in the caller's environment would turn off or change the pathspec magic
    # (GIT_LITERAL_PATHSPECS=1 makes `:(icase,literal)PACKAGES` match nothing: untracked, allowed).
    for k in ("GIT_LITERAL_PATHSPECS", "GIT_GLOB_PATHSPECS", "GIT_NOGLOB_PATHSPECS", "GIT_ICASE_PATHSPECS"):
        env.pop(k, None)
    r = subprocess.run(["git", "-C", str(wt), "ls-files", "--", f":(icase,literal){top}"],
                       capture_output=True, text=True, env=env)
    return r.returncode == 0 and not r.stdout.strip()


def lane_copy(p):
    """True for the lane folder and descendants, TEAM_ROOT/wo/<lane>/<name> and
    descendants, and paths under TEAM_ROOT containing /.claude/worktrees/. SWT must
    be the standing workcrews/<lane>/<swt> worktree even for a subagent in a
    work-order tree, so TEAM_ROOT is the team folder."""
    if not LANE_DIR:
        return False
    lane = str(LANE_DIR)
    if p == lane or p.startswith(lane + "/"):
        return True
    if LANE and TEAM_ROOT and re.match(re.escape(str(TEAM_ROOT)) + r"/wo/" + re.escape(LANE) + r"/[^/]+(/|$)", p):
        return True
    return bool(TEAM_ROOT) and p.startswith(str(TEAM_ROOT) + "/") and "/.claude/worktrees/" in p


def repo_rel(p):
    wt = worktree_root(p)
    if wt is None:
        return None
    rel = os.path.relpath(p, wt)
    return "" if rel == "." else rel


def in_zone_rel(rel):
    return lane_rule().in_area(rel)


def in_lane_scratch(p):
    """True when p's real path is the lane's scratchpad/ or ledger/ or under them.
    realpath because not every caller resolves first (check_build_tool passes the
    hook's cwd): a symlink in the scratchpad must not stand for its target."""
    if not LANE_DIR:
        return False
    real = os.path.realpath(p)
    return any(real == str(LANE_DIR / d) or real.startswith(str(LANE_DIR / d) + "/") for d in ("scratchpad", "ledger"))


def classify(p):
    """'free' (not a folder we guard), 'own' (the lane's ledger, scratchpad, records, `.claude/`,
    or an untracked file at a worktree's top), 'zone', or 'outside'."""
    if not protected(p):
        return "free"
    if not lane_copy(p):
        return "outside"
    # The lane's scratchpad and ledger are its own whatever they hold: a git clone
    # kept there (a benchmark checkout, a replayed repo) has a .git that
    # worktree_root would take for a lane worktree and class outside. Commits and
    # pushes from such a clone are refused in check_git.
    if in_lane_scratch(p):
        return "own"
    if "/.claude/" in p or p.endswith("/.claude"):
        return "own"
    rel = repo_rel(p)
    if rel is None:
        return "own"
    if refused_by(rel, lane_rule()) is None:
        return "zone"
    if (rel.startswith(".claude/") or rel == ".ledger.md" or rel.startswith("cargo-target")
            or re.fullmatch(r"\.test-record-[0-9a-f]+\.json", rel)):
        return "own"
    if untracked_root_file(p):
        return "own"
    return "outside"


_OWNED_DOC_PARENTS = tuple(dict.fromkeys(os.path.dirname(d) for d in OWNED_DOC_DIRS))


def holds_zone(p):
    """A folder that contains the zone or its docs (packages, apps, docs): staging it is fine.
    The docs folders are `docs`, each OWNED_DOC_DIRS folder and their parents (docs/_public,
    docs/internal), so staging a parent behaves the same for every reference folder."""
    rel = repo_rel(p)
    if rel is None:
        return False
    rel = rel.rstrip("/")
    return rel in ("", ".") or ZONE.startswith(rel + "/") or rel in ("docs", *OWNED_DOC_DIRS, *_OWNED_DOC_PARENTS)


def orchestrator_owned_path(p):
    """True when p (resolved) is in a lane copy and its repo-relative path is one the manifest's
    orchestrator_owns names. A path outside the lane's copies is never one."""
    rel = repo_rel(p) if lane_copy(p) else None
    return rel is not None and lane_rule().orchestrator_owned(rel)


def refuses_write(p):
    """True when a write to p (resolved) is refused for this lane. An unwalled whole-repo lane
    (orc_only) is refused only an orchestrator_owns path that classify calls "outside", so its
    "own" carve-outs (scratchpad, ledger, .claude, untracked top files, ...) and its "free"
    (outside the workspace and the codeteam checkout) hold as for any lane. Any other lane is refused what
    classify calls "outside"."""
    if orc_only():
        return orchestrator_owned_path(p) and classify(p) == "outside"
    return classify(p) == "outside"


def check_write(path, cwd, how):
    if not path or path.startswith("-") or "$" in path or path in ("/dev/null", "/dev/stdout", "/dev/stderr"):
        return
    if cwd is None and not os.path.isabs(os.path.expanduser(path)):
        return   # after `cd $VAR` the folder is unknown
    p = resolve(path, cwd)
    if refuses_write(p):
        deny(f"{how} `{p}`")


# ---------------------------------------------------------------- shell parsing

HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1[^\n]*\n.*?\n[ \t]*\2[ \t]*(?=\n|$)", re.S)


def strip_heredocs(cmd):
    return HEREDOC.sub(lambda m: m.group(0).split("\n", 1)[0], cmd)


def tokens(cmd):
    cmd = strip_heredocs(cmd).replace("\\\n", " ").replace("\n", " ; ")
    lx = shlex.shlex(cmd, posix=True, punctuation_chars=";&|<>()")
    lx.whitespace_split = True
    lx.commenters = ""
    return list(lx)


def segments(toks):
    seg, out = [], []
    for t in toks:
        if t in SEPARATORS or re.fullmatch(r"[;&|()]+", t):
            if seg:
                out.append(seg)
            seg = []
        else:
            seg.append(t)
    if seg:
        out.append(seg)
    return out


def is_redirect(t):
    return bool(re.fullmatch(r"&?>{1,2}[|&]?", t))


def split_redirects(seg):
    words, targets, i = [], [], 0
    while i < len(seg):
        t = seg[i]
        nxt = seg[i + 1] if i + 1 < len(seg) else None
        if t.isdigit() and nxt is not None and (is_redirect(nxt) or nxt.startswith("<")):
            i += 1
            continue
        if is_redirect(t):
            if nxt is not None and not t.endswith("&") and not re.fullmatch(r"[0-9-]+", nxt):
                targets.append(nxt)
            i += 2
            continue
        if t.startswith("<"):
            i += 2
            continue
        words.append(t)
        i += 1
    return words, targets


def strip_prefix(words):
    """Drop VAR=val assignments and wrappers (env, timeout 600, caffeinate -i, ...)."""
    envs, i = {}, 0
    while i < len(words):
        w = words[i]
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", w)
        if m:
            envs[m.group(1)] = m.group(2)
            i += 1
            continue
        base = os.path.basename(w)
        if base == "command" and i + 1 < len(words) and words[i + 1] in ("-v", "-V"):
            return envs, []
        if base in WRAPPERS:
            i += 1
            while i < len(words) and words[i].startswith("-"):
                opt = words[i]
                i += 1
                if base == "env":
                    # env's options that take a value. -C/--chdir moves the folder the
                    # command runs in, -S/--split-string carries a command line; both go
                    # back to check_segment under keys no shell variable can have.
                    key = {"-C": " cwd", "--chdir": " cwd", "-S": " split", "--split-string": " split"}
                    name, eq, val = opt.partition("=")
                    if eq and name in key:
                        envs[key[name]] = val
                    elif opt in key and i < len(words):
                        envs[key[opt]] = words[i]; i += 1
                    elif opt in ("-u", "--unset", "-P") and i < len(words):
                        i += 1
                    continue
                if base in ("nice", "timeout", "gtimeout") and opt in ("-n", "-s", "-k") and i < len(words):
                    i += 1
            if base in ("timeout", "gtimeout") and i < len(words) and re.fullmatch(r"[0-9.]+[smhd]?", words[i]):
                i += 1
            continue
        break
    return envs, words[i:]


# ---------------------------------------------------------------- the checks

def make_start_dir(args: list[str], cwd: str | None) -> str | None:
    """Use the lane worktree for unknown cwd unless a directory option is present."""
    if cwd is None and not any(a == "-C" or a.startswith("-C") or a.startswith("--directory") for a in args):
        cwd = SWT   # unknown folder: judge it as the lane's own worktree
    return cwd


def make_dir_arg(args: list[str], i: int) -> tuple[str | None, int]:
    """Return the directory and words consumed, or (None, 0) if no form matches."""
    a = args[i]
    if a in ("-C", "--directory") and i + 1 < len(args):
        return args[i + 1], 2
    if a.startswith("--directory="):
        return a.split("=", 1)[1], 1
    if a.startswith("-C") and len(a) > 2:
        return a[2:], 1
    return None, 0


def make_option_width(args: list[str], i: int) -> int:
    """Return the option's word count, or zero, so arguments are not treated as targets."""
    a = args[i]
    if a in MAKE_ARG_OPTIONS and i + 1 < len(args):
        return 2
    if a in ("-j", "-l") and i + 1 < len(args) and args[i + 1].isdigit():
        return 2
    if a.startswith("-"):
        return 1
    return 0


def parse_make_args(args: list[str], cwd: str | None, envs: dict[str, str]) -> tuple[str | None, dict[str, str], list[str]] | None:
    """Return directory, variables and targets, or None for a recognized print-only flag.

    Resolve successive directory options against the directory reached so far.
    """
    mdir, vars_, targets, i = make_start_dir(args, cwd), dict(envs), [], 0
    while i < len(args):
        a = args[i]
        folder, taken = make_dir_arg(args, i)
        if taken:
            mdir = resolve(folder, mdir); i += taken; continue
        if a in MAKE_PRINT_ONLY:
            return None   # skip make checks for recognized dry-run and question flags
        width = make_option_width(args, i)
        if width:
            i += width; continue
        m = MAKE_VAR_RE.match(a)
        if m:
            vars_[m.group(1)] = m.group(2); i += 1; continue
        targets.append(a); i += 1
    return mdir, vars_, targets


def check_make_vars(vars_: dict[str, str]) -> None:
    for k in LOCKED_VARS:
        if k in vars_:
            deny(f"make with {k}= (it would let a zone target run other code)")
    if "ZONE" in vars_ and vars_["ZONE"].strip().strip("/") != ZONE:
        deny(f"make ZONE={vars_['ZONE']}")


def check_make_dir(vars_: dict[str, str], mdir: str | None, root: str, rel_m: str | None) -> bool:
    """Check DIR against lane boundaries; return True for a DIR containing '$'.

    True makes the caller skip the own-Makefile and target checks as well.
    """
    if "DIR" in vars_:
        d = vars_["DIR"].strip().rstrip("/") or "."
        if "$" in d:
            return True
        if os.path.isabs(os.path.expanduser(d)):
            if classify(resolve(d, root)) == "outside":
                deny(f"make DIR={d}")
        else:
            base = mdir if (rel_m and in_zone_rel(rel_m)) else root
            rel = os.path.relpath(resolve(d, base), root)
            if not in_zone_rel(rel):
                deny(f"make DIR={d}")
    return False


def check_make(args: list[str], cwd: str | None, envs: dict[str, str]) -> None:
    parsed = parse_make_args(args, cwd, envs)
    if parsed is None:
        return
    mdir, vars_, targets = parsed
    if not protected(mdir):
        return
    if not lane_copy(mdir):
        deny(f"make in `{mdir}` (not one of this lane's worktrees)")
    check_make_vars(vars_)
    root = str(worktree_root(mdir) or mdir)
    rel_m = repo_rel(mdir)
    if check_make_dir(vars_, mdir, root, rel_m):
        return
    if rel_m and in_zone_rel(rel_m) and (Path(mdir) / "Makefile").exists():
        return   # the zone's own Makefile
    check_make_targets(targets, vars_)


def check_make_targets(targets: list[str], vars_: dict[str, str]) -> None:
    """Refuse unscoped targets and whole-product targets unavailable to the lane."""
    for tgt in targets or ["help"]:
        if tgt.startswith("$"):
            continue
        if tgt in SCOPED_TARGETS:
            var = SCOPED_TARGETS[tgt]
            if var not in vars_:
                deny(f"make {tgt} without {var}= (it would reach the whole product; give {var}=<a path in your zone>)")
            continue
        if tgt in zone_targets():
            continue
        if tgt not in LANE_TARGETS:
            deny(f"make target `{tgt}` (a whole-product target; lanes run make zone-test, "
                 "zone-test-one, zone-test-status, zone-check DIR=<zone>, warm, test-one DIR=<zone>)")


def check_build_tool(words, cwd):
    cwd = cwd or SWT
    tool = os.path.basename(words[0])
    sub = next((w for w in words[1:] if not w.startswith("-") and not w.startswith("+")), "")
    if tool != "xcodebuild" and sub not in ("test", "build", "run", "bench", "nextest", "check", "clippy"):   # cargo/swift subcommands
        return
    where = cwd
    for i, w in enumerate(words):
        if w in ("--manifest-path", "--package-path", "-project", "-workspace") and i + 1 < len(words):
            where = resolve(words[i + 1], cwd)
        elif w.startswith("--manifest-path=") or w.startswith("--package-path="):
            where = resolve(w.split("=", 1)[1], cwd)
    if classify(where) == "outside":
        deny(f"`{tool} {sub}` in `{where}`")


# The runner's helpers that take a package or crate folder as their first argument.
DIR_HELPERS = ("test-times.py", "swift-test-xcode")


def check_dir_helper(words, cwd):
    cwd = cwd or SWT
    i = next((j for j, w in enumerate(words) if os.path.basename(w) in DIR_HELPERS), None)
    if i is None:
        return
    tool = os.path.basename(words[i])
    target = next((w for w in words[i + 1:] if not w.startswith("-")), None)
    if target is None or "$" in target or "`" in target:
        return
    if classify(resolve(target, cwd)) == "outside":
        deny(f"`{tool}` on `{target}`")


def path_args(args):
    return [a for a in args if a and not a.startswith("-")]


def check_sed_perl(cmd, args, cwd):
    if cmd == "perl":
        inplace = any(re.fullmatch(r"-[a-zA-Z]*i\S*", a) for a in args)
    else:
        inplace = any(a == "--in-place" or re.fullmatch(r"-[a-zA-Z]*i\S*", a) for a in args)
    if not inplace:
        return
    has_e = any(a in ("-e", "-f", "--expression") or (cmd == "perl" and a.startswith("-") and "e" in a[1:]) for a in args)
    rest, i = [], 0
    while i < len(args):
        a = args[i]
        if a in ("-e", "-f", "--expression") or (cmd == "perl" and a.startswith("-") and a.endswith("e")):
            i += 2; continue
        if a.startswith("-") or a == "":
            i += 1; continue
        rest.append(a); i += 1
    if not has_e and rest:
        rest = rest[1:]   # the script
    for a in rest:
        check_write(a, cwd, f"{cmd} -i on")


def check_git(args, cwd, envs=None):
    gcwd, i = cwd, 0
    # Folders git may act on besides gcwd: --git-dir/--work-tree and GIT_DIR/GIT_WORK_TREE.
    others = [v for k, v in (envs or {}).items() if k in ("GIT_DIR", "GIT_WORK_TREE")]
    aliases = {}   # alias.NAME=VALUE from -c, which git applies before the clone's config
    while i < len(args) and args[i].startswith("-"):
        a = args[i]
        if a == "-C" and i + 1 < len(args):
            gcwd = None if "$" in args[i + 1] else resolve(args[i + 1], gcwd or SWT); i += 2; continue
        if a in ("--git-dir", "--work-tree") and i + 1 < len(args):
            others.append(args[i + 1]); i += 2; continue
        if a.startswith("--git-dir=") or a.startswith("--work-tree="):
            others.append(a.split("=", 1)[1]); i += 1; continue
        if a == "-c" and i + 1 < len(args):
            k, _, v = args[i + 1].partition("=")
            if k.lower().startswith("alias."):
                aliases[k[6:].lower()] = v
            i += 2; continue
        if a in ("--namespace", "--exec-path", "--config-env", "--attr-source"):
            i += 2; continue
        i += 1
    if i >= len(args):
        return
    # A lane's work reaches exchange only from its worktree, through
    # push-up. A clone in the lane's scratchpad or ledger is the lane's own to
    # edit, so a commit or push from it would carry edits around the zone.
    # Covered: -C, --git-dir/--work-tree, GIT_DIR/GIT_WORK_TREE set on the command
    # or by `env` (with env -C), aliases from -c or the clone's config. Accepted
    # fail-open, like the guard's other checks: a folder from a variable
    # (`cd $S`, `-C "$S"`), an `export`ed GIT_DIR, git run through xargs or
    # find -exec. Other ways to make or move commits (merge, cherry-pick,
    # commit-tree, send-pack, a pull from the clone into the worktree) are
    # outside this rule and not refused here. An unwalled whole-repo lane is not
    # checked for it.
    where = [gcwd or SWT] + [resolve(o, gcwd or SWT) for o in others if "$" not in o]
    if not orc_only() and any(in_lane_scratch(w) for w in where):
        sub = args[i]
        if sub == "config":
            # The hook sees `git config alias.ci commit && git ci` before the config
            # exists, so the alias is refused where it is set.
            rest = args[i + 1:]
            for j, k in enumerate(rest):
                if k.lower().startswith("alias.") and j + 1 < len(rest):
                    aliases[k[6:].lower()] = rest[j + 1]
                    sub = k[6:]
                    break
            else:
                return
        for _ in range(5):   # an alias may name another alias
            if sub in ("commit", "push"):
                deny(f"git {args[i]} from a repository in the lane's scratchpad or ledger ("
                     "work reaches exchange only from the lane's worktree, through push-up)")
            exp = aliases.get(sub.lower())
            if exp is None:
                r = subprocess.run(["git", "-C", str(where[0]), "config", "--get", f"alias.{sub}"],
                                   capture_output=True, text=True)
                exp = r.stdout.strip() if r.returncode == 0 else None
            if not exp:
                break
            if exp.startswith("!"):
                deny(f"git alias `{sub}` runs a shell command in a repository in the lane's scratchpad or "
                     "ledger (no commit or push from there)")
            try:
                sub = shlex.split(exp)[0]
            except (ValueError, IndexError):
                break
        return
    if args[i] not in ("add", "rm", "mv"):
        return
    sub, rest = args[i], args[i + 1:]
    after_dd = rest[rest.index("--") + 1:] if "--" in rest else None
    cands = after_dd if after_dd is not None else path_args(rest)
    for a in cands:
        if a in (".", ":/", "-A") or a.startswith(":") or a.startswith("$"):
            continue
        if gcwd is None and not os.path.isabs(a):
            continue
        p = resolve(a, gcwd)
        # Only add, rm and mv reach this loop (the return above), so the two checks below
        # never fire today; they matter only if restore or checkout is added to that list.
        if sub == "checkout" and after_dd is None and not os.path.exists(p):
            continue   # a branch, not a path
        if sub in ("restore", "checkout"):
            continue   # undoing a change to a committed state is always fine
        if not os.path.isfile(p) and holds_zone(p):
            continue
        if refuses_write(p):
            deny(f"git {sub} on `{a}`")


def check_segment(seg, cwd):
    words, redirs = split_redirects(seg)
    for r in redirs:
        check_write(r, cwd, "writing")
    envs, words = strip_prefix(words)
    if " split" in envs:   # env -S 'cmd args' [more args]: check the command it runs
        check_command(" ".join([envs[" split"], *map(shlex.quote, words)]), envs.get(" cwd") and resolve(envs[" cwd"], cwd or SWT) or cwd)
        return cwd
    if not words:
        return cwd
    if " cwd" in envs:     # env -C DIR cmd: cmd runs in DIR; the shell's own folder is unchanged
        here = None if "$" in envs[" cwd"] else resolve(envs[" cwd"], cwd or SWT)
        check_segment(words, here)
        return cwd
    cmd = os.path.basename(words[0])
    args = words[1:]
    if cmd in ("cd", "pushd"):
        tgt = next((a for a in args if not a.startswith("-")), str(HOME))
        if "$" in tgt or "`" in tgt or (cwd is None and not os.path.isabs(tgt)):
            return None
        return resolve(tgt, cwd)
    if cmd in ("bash", "sh", "zsh"):
        for j, a in enumerate(args):
            if re.fullmatch(r"-[a-z]*c[a-z]*", a) and j + 1 < len(args):
                check_command(args[j + 1], cwd)
                break
        return cwd
    if active():
        check_test_route(words)
    if cmd == "eval":
        check_command(" ".join(args), cwd)
    elif (walls() or orc_only()) and (cmd in ("make", "gmake", "cargo", "swift", "xcodebuild", *DIR_HELPERS)
                                      or cmd.startswith("python")):
        pass        # a whole-repo lane runs and builds anything; only its writes are checked (walled: another lane's folders, orc_only: orchestrator_owns)
    elif cmd in ("make", "gmake"):
        check_make(args, cwd, envs)
    elif cmd in ("cargo", "swift", "xcodebuild"):
        check_build_tool(words, cwd)
    elif cmd in DIR_HELPERS or (cmd.startswith("python") and any(os.path.basename(a) in DIR_HELPERS for a in args)):
        check_dir_helper(words, cwd)
    elif cmd == "tee":
        for a in path_args(args):
            check_write(a, cwd, "writing")
    elif cmd in ("sed", "gsed", "perl"):
        check_sed_perl(cmd, args, cwd)
    elif cmd in ("cp", "mv", "rsync", "install", "ln", "ditto"):
        pa = path_args(args)
        if pa:
            dest = pa[-1]
            dp = resolve(dest, cwd) if (cwd or os.path.isabs(dest)) and "$" not in dest else None
            if dp and os.path.isdir(dp) and holds_zone(dp) and len(pa) > 1:
                for src in pa[:-1]:      # into a folder: judge each file where it lands
                    check_write(os.path.join(dp, os.path.basename(src)), cwd, f"{cmd} into")
            else:
                check_write(dest, cwd, f"{cmd} into")
        if cmd == "mv":
            for a in pa[:-1]:
                check_write(a, cwd, "mv from")
    elif cmd in ("rm", "rmdir", "touch", "truncate", "unlink", "patch"):
        for a in path_args(args):
            check_write(a, cwd, cmd)
    elif cmd == "git":
        check_git(args, cwd, envs)
    return cwd


def check_command(cmd, cwd):
    try:
        toks = tokens(cmd)
    except ValueError:
        log("parse_fail_open", cmd[:200].replace("\n", " "))
        return
    for seg in segments(toks):
        cwd = check_segment(seg, cwd)


def git_subcommand(args):
    """The git subcommand in args, after git's global options. Skips the same options check_git's loop
    does (-C, -c, --git-dir, --work-tree and their =value forms, --namespace, --exec-path,
    --config-env, --attr-source) but only to find the subcommand; it checks nothing."""
    i = 0
    while i < len(args) and args[i].startswith("-"):
        a = args[i]
        if a in ("-C", "--git-dir", "--work-tree", "-c") and i + 1 < len(args):
            i += 2; continue
        if a in ("--namespace", "--exec-path", "--config-env", "--attr-source"):
            i += 2; continue
        i += 1
    return args[i] if i < len(args) else None


SHELL_KEYWORDS = ("if", "then", "do", "else", "elif", "while", "until", "!")


def runs_push(cmd):
    """True when the command runs a push (git push, codeteam/codeteam2 push-up) or a ledger close
    (zone-tool ledger close). A push counts only when a command runs one: naming push-up in text,
    quotes, heredocs, -m messages or say lines does not (it once caused five false stops). Each command
    segment is looked at after shell keywords (then, do, ...), redirects, VAR= and wrappers (env,
    timeout, ...) are dropped. It unwraps `env -S`, python running a script, bash/sh/zsh -c and
    eval. Returns False when the command cannot be tokenised."""
    try:
        toks = tokens(cmd)
    except ValueError:
        return False
    for seg in segments(toks):
        words, _ = split_redirects(seg)
        while words and words[0] in SHELL_KEYWORDS:
            words = words[1:]
        envs, words = strip_prefix(words)
        if " split" in envs and runs_push(" ".join([envs[" split"], *map(shlex.quote, words)])):
            return True
        if not words:
            continue
        name, args = os.path.basename(words[0]), words[1:]
        if name.startswith("python"):
            script = next((j for j, a in enumerate(args) if not a.startswith("-")), None)
            if script is None:
                continue
            name, args = os.path.basename(args[script]), args[script + 1:]
        if name in ("bash", "sh", "zsh"):
            for j, a in enumerate(args):
                if re.fullmatch(r"-[a-z]*c[a-z]*", a) and j + 1 < len(args):
                    if runs_push(args[j + 1]):
                        return True
                    break
            continue
        if name == "eval":
            if runs_push(" ".join(args)):
                return True
            continue
        if name == "git" and git_subcommand(args) == "push":
            return True
        if name in ("codeteam", "codeteam2") and next((a for a in args if not a.startswith("-")), None) == "push-up":
            return True
        if name == "zone-tool" and args[:2] == ["ledger", "close"]:
            return True
    return False


def decide(name, inp, cwd):
    """None when allowed, else the reason."""
    try:
        if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
            path = inp.get("file_path") or inp.get("notebook_path") or inp.get("path") or ""
            check_write(path, cwd, f"{name} of")
        elif name == "Bash":
            check_command(inp.get("command", ""), cwd)
    except Denied as e:
        return str(e)
    return None


def mode_pretool(d):
    global AGENT_ID
    AGENT_ID = d.get("agent_id") or ""
    why = decide(d.get("tool_name", ""), d.get("tool_input", {}) or {}, d.get("cwd") or os.getcwd())
    if why and why.startswith(TEST_ROUTE):
        log("block", why)
        print(f"Test guard ({LANE} lane): {why[len(TEST_ROUTE):]}. Never re-run a test to be sure: "
              "a record that matches is the answer (`make zone-test-status`).", file=sys.stderr)
        sys.exit(2)
    if why:
        log("block", why)
        if orc_only():
            print(f"Zone guard: {why} belongs to the orchestrator ({ORC}): the team manifest's "
                  f"orchestrator_owns names it ({LANE} lane). A change there goes to {ORC} as a NOTE "
                  "naming the file and what it needs.", file=sys.stderr)
            sys.exit(2)
        where = "in another lane's folder" if walls() else f"outside zone `{ZONE}`"
        print(f"Zone guard: {why} is {where} ({LANE} lane). " + rule_text(), file=sys.stderr)
        sys.exit(2)


# ---------------------------------------------------------------- context and compaction

def staff_session():
    """An orchestrator, designer or guard session codeteam started (no lane worktree): it gets the compaction
    prompt and the /compact after its handoff too: every agent refocuses before compacting."""
    return bool(LANE) and not SWT and bool(os.environ.get("CODETEAM_MANIFEST"))


def state_file():
    if LANE_DIR:
        return LANE_DIR / "ledger" / "ctx-state.json"
    return CT_HOME / "run" / "ctx" / f"{Path(os.environ.get('CODETEAM_MANIFEST', 'x')).stem}-{LANE}.json"


def load_state():
    try:
        return json.loads(state_file().read_text())
    except (OSError, ValueError):
        return {}


def save_state(s):
    try:
        state_file().parent.mkdir(parents=True, exist_ok=True)
        state_file().write_text(json.dumps(s))
    except OSError:
        pass


def tail_lines(path, size=600_000):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            end = f.tell()
            f.seek(max(0, end - size))
            return f.read().decode("utf-8", "ignore").splitlines()
    except OSError:
        return []


def context_tokens(transcript):
    for line in reversed(tail_lines(transcript)):
        if '"usage"' not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") != "assistant" or d.get("isSidechain"):
            continue
        u = (d.get("message") or {}).get("usage") or {}
        return sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens",
                                                 "cache_creation_input_tokens", "output_tokens"))
    return None


def manifest():
    m = os.environ.get("CODETEAM_MANIFEST")
    if m:
        return m
    name = TEAM_ROOT.name if TEAM_ROOT else ""
    return str(CT_HOME / "teams" / f"{name.removeprefix('team-')}.toml")


def post(kind, text):
    try:
        subprocess.Popen([CT_BIN, "say", manifest(), LANE, "codeteam", kind, LANE, text],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


def mode_context(d):
    if d.get("agent_id"):
        return   # a subagent's tool call; the session's own context is what is measured
    tr = d.get("transcript_path")
    if not tr:
        return
    used = context_tokens(tr)
    window = int(os.environ.get("CODETEAM_CTX_WINDOW") or 200000)
    if not used:
        return
    old = load_state()
    s = dict(old)
    sid = d.get("session_id", "")
    if s.get("session") != sid or used < window * 0.4:
        s = {"session": sid}          # a new session, or it has compacted since
    if used < window * PREPARE_AT or s.get("prompted"):
        if s != old:
            save_state(s)
        return
    pct = round(100 * used / window)
    s.update(prompted=time.time(), at=used)
    save_state(s)
    hhmm = time.strftime("%H:%M")
    text = (f"Context check ({hhmm}): your context is at {pct}% of its {window // 1000}k window and "
            "compacts on its own at 100%. Finish the step you are on and start no new one. Then, in this "
            "order: first /refocus (read and follow .claude/skills/refocus/SKILL.md: the "
            "four-part report as your whole message), then /prepare-for-compact (read and follow "
            ".claude/commands/prepare-for-compact.md: the handoff). When you end with 'Ready. Run /compact now.', "
            "codeteam runs /compact, keeping the Refocus report and the handoff, and then tells you to resume.")
    # Not posted as an inbox message: unread mail makes codeteam's wake relaunch a sleeping lane,
    # which brought a team's lanes back after the owner had stopped them.
    log("prepare", f"{pct}% of {window}")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}}))


def turn_lines(transcript):
    """Transcript lines since the last prompt the session was given."""
    lines = tail_lines(transcript, 2_000_000)
    start = 0
    for i, line in enumerate(lines):
        if '"user"' not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        c = (d.get("message") or {}).get("content")
        if d.get("type") == "user" and not d.get("isSidechain") and (
                isinstance(c, str) or (isinstance(c, list) and any(isinstance(x, dict) and x.get("type") == "text" for x in c))):
            start = i
    return lines[start:]


def last_reply(lines):
    """The text of the last main-thread assistant record with text among the turn's lines; "" when none."""
    for line in reversed(lines):
        try:
            x = json.loads(line)
        except ValueError:
            continue
        if x.get("type") == "assistant" and not x.get("isSidechain"):
            content = (x.get("message") or {}).get("content", [])
            parts = [c.get("text", "") for c in content if isinstance(c, dict)] if isinstance(content, list) else [str(content)]
            text = " ".join(parts)
            if text.strip():
                return text
    return ""


def mode_stop(d):
    tr = d.get("transcript_path")
    if not tr:
        return
    lines = turn_lines(tr)
    s = load_state()
    # 1. The handoff is written: codeteam runs /compact, then the resume line.
    if s.get("prompted") and not s.get("compact_sent"):
        # The hook can run before Claude Code has written the turn's last reply to the transcript (seen once: the
        # handoff ended 'Run /compact now', the hook saw the reply before it, and /compact never ran). Take the reply from the hook's input when given; otherwise read again for up to 3 s.
        last_text = str(d.get("last_assistant_message") or "") or last_reply(lines)
        deadline = time.time() + 3
        while "Run /compact now" not in last_text and time.time() < deadline:
            time.sleep(0.25)
            last_text = last_reply(turn_lines(tr))
        if "Run /compact now" in last_text:
            s["compact_sent"] = time.time()
            save_state(s)
            log("compact_now", "handoff posted")
            subprocess.Popen([CT_BIN, "compact-now", manifest(), LANE, tr],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return
    # 2. Work went out this turn with no note after it: back once to file it. Work went out
    # means a command that runs a push or a ledger close (runs_push), not text that names one.
    # A note is a call to a tool whose name contains one of CODETEAM_NOTE_TOOLS; with none set, no check.
    if d.get("stop_hook_active") or not lane_session() or not NOTE_TOOLS:
        return
    pushed, filed_after = False, False
    for line in lines:
        if '"tool_use"' not in line:
            continue
        try:
            x = json.loads(line)
        except ValueError:
            continue
        if x.get("isSidechain"):
            continue
        content = (x.get("message") or {}).get("content", [])
        for c in content if isinstance(content, list) else []:
            if not isinstance(c, dict) or c.get("type") != "tool_use":
                continue
            if c.get("name") == "Bash" and runs_push((c.get("input") or {}).get("command", "")):
                pushed, filed_after = True, False
            elif any(t in c.get("name", "") for t in NOTE_TOOLS):
                if pushed:
                    filed_after = True
    if pushed and not filed_after:
        log("note_missing", "push or close with no note")
        print(json.dumps({"decision": "block", "reason": (
            "You pushed or closed a request this turn and filed no note after it. Do your role "
            "file's Close step now: file the note for this work (what changed in your zone, why, "
            "and what is left), then end your turn.")}))


def zone_brief(source):
    zdir = Path(SWT) / ZONE
    spec = ""
    for f in (zdir / "docs" / "SPEC.md", zdir / "README.md"):
        if f.exists():
            body = "\n".join(f.read_text(errors="ignore").splitlines()[:40]).strip()
            spec = f"What this zone is (the first lines of `{os.path.relpath(f, SWT)}`):\n{body[:2500]}"
            break
    docs = []
    for sub in ("docs/reference", "docs/internal/reference"):
        ref = Path(SWT) / sub
        if ref.is_dir():
            docs += sorted(f"{sub}/{f.name}" for f in ref.glob("*.md") if owns_doc(f"{sub}/{f.name}"))
    if docs:
        spec += ("\n\n" if spec else "") + "Your zone's SPEC and INTERFACE: " + ", ".join(f"`{d}`" for d in docs) + "."
    handoff = LANE_DIR / "ledger" / "reports" / "handoff.md"
    hand = (f"Your handoff file: `{handoff}` (written "
            f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(handoff.stat().st_mtime))})."
            if handoff.exists() else "No handoff file yet.")
    product = TEAM_ROOT.name.removeprefix("team-") if TEAM_ROOT else "the product"
    parts = [f"## Your zone: `{ZONE}` ({LANE} lane, team {product})",
             "You are this zone's expert: its code, its SPEC and INTERFACE, its history and its place in "
             "the product. The repo is checked out whole only so the zone can build.",
             rule_text(), spec, hand,
             "Notes: keep your notes as your role file directs, and before a compaction /refocus then "
             "/prepare-for-compact (codeteam prompts you at 70% of the compaction window)."]
    if source == "compact":
        parts.append("You have just compacted. Before anything else, do steps 1-3 of "
                     ".claude/commands/recover-from-compact.md (find your handoff, walk back if needed, check "
                     "the repo), then carry on with the work in progress. Step 4's 'wait' does not apply to a "
                     "lane session.")
    return "\n\n".join(p for p in parts if p)


def mode_start(d):
    source = d.get("source", "")
    if source == "compact":
        save_state({"session": d.get("session_id", "")})
    if active():
        print(zone_brief(source))
    elif source == "compact":
        handoff = LANE_DIR / "ledger" / "reports" / "handoff.md"
        print(f"You ({LANE} lane) have just compacted. Before anything else, do steps 1-3 of "
              ".claude/commands/recover-from-compact.md (find your handoff, walk back if needed, check the "
              f"repo), then carry on with the work in progress; step 4's 'wait' does not apply to a lane "
              f"session. Your handoff file: `{handoff}`.")
    log("brief", source)


def mode_subagent(d):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": rule_text()}}))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    # walls() already builds lane_rule() (team.json, zone-docs.json, the manifest TOML, cached in
    # _WALLS) for every "." lane session, so orc_only() adds no reads; on a manifest without
    # orchestrator_owns it is False and the pretool hook returns early.
    if not (active() or (walls() and mode in ("pretool", "subagent"))
            or (orc_only() and mode == "pretool")
            or (lane_session() and mode in ("context", "stop", "start"))
            or (staff_session() and mode in ("context", "stop"))):
        return
    try:
        d = json.load(sys.stdin)
    except ValueError:
        d = {}
    {"pretool": mode_pretool, "context": mode_context, "stop": mode_stop,
     "start": mode_start, "subagent": mode_subagent}.get(mode, lambda _: None)(d)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:   # fail open, logged
        log("error_fail_open", f"{type(e).__name__}: {e}")
        sys.exit(0)
