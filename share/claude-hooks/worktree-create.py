#!/usr/bin/env python3
"""WorktreeCreate (global): where agent worktrees go.

Team sessions (the repo is a bare store under $CODETEAM_WORKSPACE/.repos, or the session runs
under $CODETEAM_WORKSPACE/team-*; the workspace defaults to ~/codeteam-work): <parent of the
session's worktree>/requests/<name>, so for a lane <workspace>/team-<x>/workcrews/<lane>/requests/<name>.
Claude Code's default (<repo>/.claude/worktrees) put them inside the store: 88 worktrees, 118 GB
in one day. Everything else: Claude Code's default place, <toplevel>/.claude/worktrees/<name>.
Same branch name (worktree-<name>), from the session's HEAD. Prints only the path."""
import json, os, subprocess, sys, time
from pathlib import Path
os.environ["PATH"] = "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:" + os.environ.get("PATH", "")
HOME = Path.home()
WORKSPACE = Path(os.environ.get("CODETEAM_WORKSPACE") or HOME / "codeteam-work")
data = json.load(sys.stdin)
name = str(data.get("name") or "").strip().replace("/", "-")
cwd = data.get("cwd") or os.getcwd()
if not name:
    sys.exit("worktree-create: no name in the hook input")
# Branch flow v5: a team whose manifest has [land] enabled = true cuts every work order tree
# from integration's tip with codeteam-land, never from the session's own tree. Before the git checks: a v5
# coordinator works in its zone folder, which is not a checkout.
manifest = os.environ.get("CODETEAM_MANIFEST", "")
if manifest and os.path.exists(manifest):
    import tomllib
    try:
        landing = (tomllib.load(open(manifest, "rb")).get("land") or {}).get("enabled")
    except (OSError, ValueError):
        landing = False
    if landing:
        zone = os.environ.get("CODETEAM_SESSION") or "orc"
        r = subprocess.run([str(Path(__file__).resolve().parents[2] / "bin" / "codeteam-land"), manifest, "wo-cut",
                            zone, name, "--staff-as-orc"], capture_output=True, text=True)
        if r.returncode:
            sys.stderr.write(r.stderr)
            sys.exit(f"worktree-create: codeteam-land wo-cut {zone} {name} failed")
        print(r.stdout.strip().splitlines()[-1])
        sys.exit(0)
g = lambda *a: subprocess.run(["git", "-C", cwd, *a], capture_output=True, text=True).stdout.strip()
top = g("rev-parse", "--show-toplevel")
if not top:
    sys.exit(f"worktree-create: {cwd} is not in a git worktree")
common = Path(g("rev-parse", "--path-format=absolute", "--git-common-dir"))
team = str(common).startswith(str(WORKSPACE / ".repos")) or str(Path(top).resolve()).startswith(str(WORKSPACE)) and "/team-" in top
# A lead already in <lane>/requests/<x> spawning its own worktree agent: its sibling,
# <lane>/requests/<name>, not <lane>/requests/requests/<name> (seen 2026-10-22).
base = Path(top).parent
if base.name == "requests":
    base = base.parent
dest = (base / "requests" / name) if team else (Path(top) / ".claude" / "worktrees" / name)
dest.parent.mkdir(parents=True, exist_ok=True)
head = g("rev-parse", "HEAD")
r = subprocess.run(["git", "-C", top, "worktree", "add", "-b", f"worktree-{name}", str(dest), head], capture_output=True, text=True)
if r.returncode:
    sys.stderr.write(r.stderr)
    sys.exit(f"worktree-create: git worktree add failed for {dest}")
mark = common / "worktree-hook"; mark.mkdir(exist_ok=True)
(mark / name).write_text(head + "\n")
# Warm a zone lane's new worktree: `make warm` copies the Rust build folder and
# compiles the zone's tests through the caches, so the lead rebuilds only what it changes. Mechanical: no agent,
# no tokens. Only for a zone lane with the Swift cache switch on (CODETEAM_SWIFT_XCODE=1).
# It runs DETACHED (2026-10-29): run inside this hook it held the Agent call that made the worktree, so a
# coordinator starting a lead was deaf to its mail for the whole warm, up to the 840 s timeout (106 of 107 lead
# starts with a warm held the session over a minute; none without). The hook takes the worktree's warm lock
# and writes the holder record into it (below) before it returns, the detached warm holds the lock until done,
# and the build queue's runner holds any build job of that worktree until the lock is free (codeteam-slot names
# the lock in its job file), so the lead's first build reuses the warm's work instead of racing it.
zone = os.environ.get("CODETEAM_ZONE", "")
# Also any lane of a team that asks for it with CODETEAM_WARM=1, whole-repo lanes included (a team whose lanes
# are all "." lanes otherwise never had a new worktree warmed, and each compiled from nothing).
if team and ((zone not in ("", ".") and os.environ.get("CODETEAM_SWIFT_XCODE") == "1")
             or os.environ.get("CODETEAM_WARM") == "1"):
    import fcntl
    log = dest.parent / f"warm-{name}.log"
    gd = subprocess.run(["git", "-C", str(dest), "rev-parse", "--path-format=absolute", "--git-dir"],
                        capture_output=True, text=True).stdout.strip()
    try:
        fd = os.open(str(Path(gd) / "codeteam-warm.lock"), os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.set_inheritable(fd, True)
        warm = ("import subprocess, sys\n"
                "with open(sys.argv[2], 'w') as f:\n"
                "    try:\n"
                "        rc = subprocess.run(['make', '--no-print-directory', 'warm'], cwd=sys.argv[1], stdout=f,\n"
                "                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, timeout=840).returncode\n"
                "    except Exception as e:\n"
                "        rc = type(e).__name__\n"
                "    print(f'warm ended: {rc}', file=f)\n")
        p = subprocess.Popen([sys.executable, "-c", warm, str(dest), str(log)], pass_fds=(fd,), start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             env=dict(os.environ, CODETEAM_WARMING="1"))
        # The holder record: the deck reads who holds this worktree's warm lock from the lock file itself,
        # without lsof. It is written through the fd this hook already holds, after Popen so the pid is the
        # warm wrapper's, and before the close so no second open or lock call is made. Best effort: a failed
        # write must never fail or delay the hook or the warm, so it is swallowed and nothing clears the record.
        try:
            rec_team = next((part for part in dest.parts if part.startswith("team-")), None)
            line = json.dumps({"pid": p.pid, "team": rec_team, "session": os.environ.get("CODETEAM_SESSION") or None,
                               "worktree": str(dest), "tool": "warm", "since": int(time.time())}) + "\n"
            os.ftruncate(fd, 0)
            os.pwrite(fd, line.encode(), 0)
        except Exception:
            pass
        os.close(fd)        # the warm holds the lock now
    except OSError as e:
        sys.stderr.write(f"worktree-create: warm not started ({e}); the worktree is usable, unwarmed\n")
# A CodeGraph index from the start, seeded from the nearest sibling worktree (about a second:
# worktrees without one sent their agents back to grep). Best effort: CodeGraph also seeds on the first query.
if team:
    try:
        subprocess.run([str(Path(__file__).resolve().parents[2] / "bin" / "codeteam-seed-index"), str(dest)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        pass
print(dest)
