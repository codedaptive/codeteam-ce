"""codeteam v1's patrol, run by the v2 loop: what the orchestrator would otherwise learn only by asking.

The checks are v1's (its lane ledgers through `lane_work`, its branch rule through `branch_leftovers`);
only the source of a session's state changes, from v1's guesses to herdr's. Findings are recorded in
team/v2/patrol.json, shown by `codeteam2 status` and the board, and the new ones ride along with the
orchestrator's next prompt instead of waking it (spend analysis, 2026-10-25: Opus request leads
waited 276 h in total; report stalls without waking the orchestrator each time).
"""
import json
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


def stalled_work_orders(land_dir, status, st, pending, now, idle_min=20, stall_min=STALL_MIN):
    """Branch flow v5 (a team once sat all day with a rework untouched since the morning, its coordinator
    asleep and the orchestrator idle, and nothing said so). One line per open work order that holds work (a commit of
    its own), is not queued for landing, has not changed for stall_min minutes, and whose
    zone's coordinator is asleep, or idle idle_min minutes, with no mail waiting. The line carries no changing number,
    so it is new once."""
    import json
    import subprocess
    from pathlib import Path
    out = []
    for f in sorted(Path(land_dir, "wo").glob("*.json")):
        if f.name.endswith((".landed.json", ".retired.json", ".bounce.txt")):
            continue
        try:
            rec = json.loads(f.read_text())
            tree, zone, wo = Path(rec["tree"]), rec["zone"], rec["wo"]
        except (OSError, ValueError, KeyError):
            continue
        if rec.get("queued") or not tree.is_dir() or zone == "orc" or wo.startswith(("docs-", "revert-")):
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
            flags += stalled_work_orders(t.root / "land", status, st, pending, now, idle_min)
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
