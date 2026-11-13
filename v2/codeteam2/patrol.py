"""codeteam v1's patrol, run by the v2 loop: what the orchestrator would otherwise learn only by asking.

The checks are v1's (its lane ledgers through `lane_work`, its branch rule through `branch_leftovers`);
only the source of a session's state changes, from v1's guesses to herdr's. Findings are recorded in
team/v2/patrol.json, shown by `codeteam2 status` and the board, and the new ones ride along with the
orchestrator's next prompt instead of waking it (spend analysis, 2026-10-25: Opus request leads
waited 276 h in total; report stalls without waking the orchestrator each time).
"""
import json
import os
import time
from pathlib import Path

READY = ("idle", "done")

TEXT = ("PATROL (codeteam, riding along): act on each line. IDLE WITH WORK or ASLEEP WITH WORK: send that lane "
        "its next queued request. DEAD LEAD: tell the lane its lead is gone and to start a new one from the lead's "
        "worktree and the order. SERIAL: tell the lane which queued requests touch different files and can run as "
        "parallel leads. BRANCHES: find whose they are; finished work's branches go (here and on GitHub), live "
        "work's get pushed. Lines: ")


STALL_MIN = 60          # a work order tree with work in it, untouched this long, with its coordinator asleep or idle
REVIEW_WAIT_H = 2       # a Stage 3 review asked for this long ago and still not answered
WAKES = ("STALLED WORK ORDER", "ASLEEP WITH WORK", "IDLE WITH WORK", "DEAD LEAD",
         "REVIEW WAITING")      # findings that wake the orchestrator


# Free space on the machine's data volume, every team's builds and shells on it (it once filled
# twice in three days and stopped every lane at once). Each level is told once on the way down; once free space
# has stayed at or above DISK_REARM_GIB for DISK_REARM_S, the warnings start again. 50 is the deck's red line. Time
# Machine's hourly local snapshot (taken at :00, released when its backup ends, :23 to :39 on 11-11/12) holds every file
# deleted while it lives, so free space falls through each window and comes back when it goes; the
# warning says so. The 2 h outlasts a window, so that swing is one episode, not a warning to every orchestrator each
# hour (five in four hours on 11-13).
DISK_WARN_GIB = (50, 20)
DISK_REARM_GIB = 80
DISK_REARM_S = 2 * 3600


def free_gib(path):
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize / 2 ** 30


def disk_warning(free, warned, manifest, levels=DISK_WARN_GIB, rearm=DISK_REARM_GIB, *, above_s=0.0,
                 rearm_s=DISK_REARM_S):
    """(the lowest level told so far, or None; the line to send now, or None). warned: that level from the last check.
    above_s: how long free space has stayed at or above rearm; warned is cleared only once that reaches rearm_s."""
    if free >= rearm:
        return (None if above_s >= rearm_s else warned), None
    crossed = [level for level in levels if free < level]
    if not crossed or (warned is not None and min(crossed) >= warned):
        return warned, None
    low = min(crossed)
    return low, (f"DISK LOW: {free:.0f} GiB free on this machine's data volume, below {low} GiB. When it fills, every "
                 f"team's builds, gates and shells stop at once. Now: run `codeteam sweep {manifest}` (it clears build "
                 "output in trees idle 2 h; it runs hourly at :23 anyway), retire finished work order trees "
                 f"(codeteam-land {manifest} wo-retire <wo>), and start no new lead until it is back above {rearm} GiB. "
                 "From :00 until its backup ends (about :25 to :40), Time Machine's hourly snapshot holds every deleted "
                 "file: a fall then comes back when the snapshot goes, and deleting frees nothing until it does "
                 ".")


def waiting_reviews(land_dir, now, hours=REVIEW_WAIT_H):
    """Branch flow v5.4 (a team's Kong once never acted on a review request and nobody
    noticed). One line per Stage 3 review in land/reviews/ still pending, asked for more than `hours` ago. The
    orchestrator is told; nothing is sent again. A new request rewrites `requested`, so its line is new once."""
    import datetime as dt
    out = []
    for f in sorted(Path(land_dir, "reviews").glob("*.json")):
        try:
            row = json.loads(f.read_text())
            if row.get("stage") != 3 or row.get("state") != "pending" or not row.get("requested"):
                continue
            asked = dt.datetime.fromisoformat(row["requested"]).timestamp()
        except (OSError, ValueError, TypeError, AttributeError):
            continue
        if now - asked < hours * 3600:
            continue
        who = sorted(n for n, r in (row.get("reviewers") or {}).items() if r == "pending")
        if not who:
            continue
        out.append(f"{row.get('zone', '?')}: REVIEW WAITING {row.get('wo', f.stem)}, asked of {', '.join(who)} at "
                   f"{row['requested']} and not answered for over {hours} h. Find out why; codeteam does not ask again.")
    return out


def last_promote(land_dir):
    """The time of the newest Stage 7 promote, from its row in land/landed.log ({"time", "promote", "to"}; rows are
    appended in order), or 0 when none is recorded."""
    import datetime as dt
    try:
        lines = Path(land_dir, "landed.log").read_text().splitlines()
    except OSError:
        return 0.0
    for line in reversed(lines):
        if '"promote"' not in line:
            continue
        try:
            return dt.datetime.fromisoformat(json.loads(line)["time"]).timestamp()
        except (ValueError, KeyError, TypeError):
            continue
    return 0.0


def landing_work_orders(listing, manifest):
    """The names a live `codeteam-land <manifest> land` process gives (its work order, each --with member and any other
    argument), from a process listing of one command line per line (`ps -axo command=`). A line counts only when its
    program is codeteam-land, run directly or by a Python: a shell wrapper, or a session whose prompt quotes the
    command, is not the land. The manifest is matched by file name, so a relative path given to the land still counts."""
    want = Path(manifest).name
    names = set()
    for line in listing.splitlines():
        words = line.split()
        at = next((i for i, w in enumerate(words[:2]) if Path(w).name == "codeteam-land"), None)
        if at is None or (at == 1 and "python" not in Path(words[0]).name.lower()):
            continue
        if len(words) < at + 3 or words[at + 2] != "land" or Path(words[at + 1]).name != want:
            continue
        for w in words[at + 3:]:
            if w.startswith("-"):
                if "=" in w:
                    names.add(w.split("=", 1)[1])
            else:
                names.add(w)
    return names


def running_lands(manifest):
    """landing_work_orders over this machine's processes now; an empty set when ps cannot be read."""
    import subprocess
    try:
        listing = subprocess.run(["ps", "-axo", "command="], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    return landing_work_orders(listing, manifest)


def stalled_work_orders(land_dir, status, st, pending, now, idle_min=20, stall_min=STALL_MIN, landing=frozenset()):
    """Branch flow v5 (a team once sat all day with a rework untouched since the morning, its coordinator
    asleep and the orchestrator idle, and nothing said so). One line per open work order that holds work (a commit of
    its own), is not queued for landing, is not held on purpose (`codeteam-land wo-hold`), has not changed
    for stall_min minutes, and whose zone's coordinator is asleep, or idle idle_min minutes, with no mail waiting. The
    line carries no changing number, so it is new once. A work order sent back by a landing conflict waits for the next
    promote and is not stalled before it. A work order a live land names (`landing`, from running_lands) is not
    stalled: Stage 2 changes nothing in its tree for the whole run."""
    import json
    import subprocess
    from pathlib import Path
    out = []
    promoted = None                     # the newest promote's time, read once and only for a bounced work order
    for f in sorted(Path(land_dir, "wo").glob("*.json")):
        if f.name.endswith((".landed.json", ".retired.json", ".bounce.txt")):
            continue
        try:
            rec = json.loads(f.read_text())
            tree, zone, wo = Path(rec["tree"]), rec["zone"], rec["wo"]
        except (OSError, ValueError, KeyError):
            continue
        if (rec.get("queued") or rec.get("held") or wo in landing or not tree.is_dir() or zone == "orc"
                or wo.startswith(("docs-", "revert-"))):
            continue
        s = status.get(zone, "absent")
        quiet = (now - (st.get(zone, {}).get("state_since") or now)) / 60
        if pending.get(zone) or not (s == "absent" or (s in READY and quiet >= idle_min)):
            continue

        def git(*a):
            return subprocess.run(["git", "-C", str(tree), *a], capture_output=True, text=True, timeout=20).stdout
        # Cheap on purpose (this runs inside the loop's tick, over every open tree): two small git calls, never a walk
        # of the tree. Work = a commit of its own; the time of its last commit is when it last moved (the index file's
        # time is no measure: any `git status` rewrites it).
        try:
            base = rec.get("base") or ""
            own = git("rev-list", "--count", f"{base}..HEAD").strip() if base else "0"
            if own in ("", "0"):
                continue                    # no commit of its own: held on purpose, or left by a cancelled start
            times = [float(git("log", "-1", "--format=%ct").strip() or 0)]
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
        # Sent back by a landing conflict (<wo>.bounce.txt) with no commit since: the landing tool told it to wait for
        # the landed work to be promoted, so it is not stalled until a promote is recorded after the bounce.
        # After that promote, a lane that does not act is reported as before.
        try:
            bounced = Path(land_dir, "wo", f"{wo}.bounce.txt").stat().st_mtime
        except OSError:
            bounced = 0.0
        if bounced >= max(times):
            if promoted is None:
                promoted = last_promote(land_dir)
            if promoted < bounced:
                continue
        if now - max(times) >= stall_min * 60:
            out.append(f"{zone}: STALLED WORK ORDER {wo}, work in its tree ({tree}) and nothing changed for over "
                       f"{stall_min} min; its coordinator is {'asleep' if s == 'absent' else 'idle'} with no mail. "
                       "Send the lane its next step.")
    return out


def findings(team, status, st, store, now=None):
    """The patrol lines for a v2 team. status: key -> herdr state; st: the loop's state per session."""
    from .team import v1
    now = now or time.time()
    t, tj = team.t, team.team_json()
    pending = {}
    for m in store.pending(held=True):
        pending[m["target"]] = pending.get(m["target"], 0) + 1
    idle_min = v1.PATROL_IDLE_MIN
    flags = []
    for n, r in sorted(tj["lanes"].items()):
        rows, active, dead, parked, queued = v1.lane_work(t, n, r, now)
        if not rows:
            continue
        s = status.get(n, "absent")
        awake = s != "absent"
        quiet = (now - (st.get(n, {}).get("state_since") or now)) / 60 if s in READY else 0
        if awake and quiet >= idle_min and not active and (queued or dead) and not pending.get(n):
            flags.append(f"{n}: IDLE WITH WORK, idle {quiet:.0f} min, {len(queued)} queued ({', '.join(queued[:3])})")
        for d in dead:
            flags.append(f"{n}: DEAD LEAD on {d}, its worktree untouched {v1.PATROL_DEAD_MIN}+ min and nothing running in it")
        if awake and len(queued) >= 2 and len(active) <= 1 and quiet < idle_min:
            flags.append(f"{n}: SERIAL, {len(active)} lead running and {len(queued)} queued ({', '.join(queued[:4])})")
        if parked:
            flags.append(f"{n}: {parked} ledger row(s) past queued with no live lead for a day or more; close or requeue them")
        if not awake and queued and not pending.get(n):
            flags.append(f"{n}: ASLEEP WITH WORK, {len(queued)} queued and no mail to wake it")
    try:
        if (t.root / "land" / "wo").is_dir():
            flags += stalled_work_orders(t.root / "land", status, st, pending, now, idle_min,
                                         landing=running_lands(team.manifest))
    except Exception:      # a patrol never fails on one check
        pass
    try:
        flags += waiting_reviews(t.root / "land", now)
    except Exception:      # a patrol never fails on one check
        pass
    try:
        el, er, um, *_ = v1.branch_leftovers(t, tj)
        if el or er or um:
            flags.append(f"BRANCHES: {len(el)} here and {len(er)} on GitHub outside the rule, {len(um)} not mirrored "
                         f"(codeteam branch-audit lists them): " + ", ".join((el + er + um)[:6]))
    except Exception:      # the branch audit needs git and the network; a patrol never fails on it
        pass
    return flags


def record(path, lines, now=None):
    """Save the current findings; return the ones not seen in the last patrol."""
    path = Path(path)
    try:
        prev = set(json.loads(path.read_text()).get("lines", []))
    except (OSError, ValueError):
        prev = set()
    path.write_text(json.dumps({"at": now or time.time(), "lines": lines}, indent=1))
    return [x for x in lines if x not in prev]


def latest(path):
    """(epoch, lines) of the last patrol, or (None, [])."""
    try:
        d = json.loads(Path(path).read_text())
        return d.get("at"), d.get("lines", [])
    except (OSError, ValueError):
        return None, []
