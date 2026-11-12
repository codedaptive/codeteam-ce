#!/bin/bash
# slow: 23 scenarios run side by side, each with several Python and stub-process starts, short jobs, event-held jobs and a one-second idle exit; allow about 8 s wall for process startup and idle waits
# zone/tests/buildq-sched.sh: bin/codeteam-buildq decides which job starts, and in what order
# (zone/docs/SPEC.md). Each scenario is a folder under a
# scratch dir with its own queue, load file, worktree and records. The stub marks its start, waits for a duration
# or a release file, then writes its record and exits. Parallel scenarios snapshot their queues and record failed
# steps and exit status; the checker names failures, and the EXIT trap prints a summary on stderr when it runs.
# Nothing here reads the live codeteam checkout: every runner runs under env -i with CODETEAM_QUEUE_DIR set to its scratch queue.
#  1. A finished run job's file has every job-file field, env included, and its env is the one it was submitted with.
#  2. A finished run job reads done, exit 0 and result PASS from its record; no record existed at its start.
#  3. The job's command runs once: one marker line.
#  4. No temporary job file is left, and every job file parses.
#  5. The child sees CODETEAM_SLOT_HELD=1, CODETEAM_BUILDQ_TICKET=<ticket> and the submitter's own environment.
#  6. The child of a dev job runs at nice 10 (the class's nice: land 0, full 2, pre/post 5, dev 10).
#  7. The child's pid is the job's pid.
#  8. The child's working directory is the job's worktree.
#  9. queue-runner.json is beside the queue, has the contract's fields and a current beat, and has no load fields.
# 10. A finished job has position null.
# 11. Budget 1 with a dev job running: a post job starts while a newer dev job waits.
# 12. The post job starts before the newer dev job.
# 13. The post job starts no later than the first dev job's finish.
# 14. The newer dev job waits for the budget: it starts after the first dev job finishes.
# 15. Budget 2: two dev jobs run at once (dev borrows past its one-job share).
# 16. A full job starts no later than the next dev finish.
# 17. A dev job queued behind the full job starts after it.
# 18. Budget 6, six dev jobs: all six run at once (dev has no ceiling).
# 19. Post's ceiling of 2 caps its borrowing: two run and the third waits.
# 20. queue.toml's budget beats CODETEAM_BUILD_BUDGET.
# 21. CODETEAM_BUILD_BUDGET sets the budget when queue.toml has none.
# 22. The budget is 6 when neither is set.
# 23. Round-robin: after a team-a start, the next place is team-b's (positions 1, 2, 3).
# 24. Round-robin: the starts run a1, b1, a2, a3.
# 25. Cost is the median of the last 5 cpu/wall ratios: 3.0, not the 4.0 of all seven lines.
# 26. A cost below 1 clamps up to 1.
# 27. A cost above the budget clamps down to the budget.
# 28. A job with an empty key takes its history from the "suite <command>" line.
# 29. A dev job with no record costs 1.
# 30. A full job with no record costs 4.
# 31. A queued job with no history has a null estimated_start.
# 32. A queued job's estimated_start is the running job's start plus its median wall, refreshed each decision.
# 33. With 500 in the load file's first line and load_max = 10 in queue.toml, a dev job is running.
# 34. In the same scenario a pre job is running.
# 35. In the same scenario a full job is running.
# 36. Swap over swap_max holds a dev start.
# 37. When swap drops under swap_max, the held dev job starts.
# 38. A warm lock held by flock holds the job it belongs to.
# 39. When the warm lock is released, that job starts.
# 40. A second runner on the same queue exits 0 at once, silently.
# 41. The second runner leaves the first runner's heartbeat in place.
# 42. --standby waits while another runner holds the queue.
# 43. --standby takes over when the runner holding the queue dies.
# 44. The runner creates the queue folder 0700.
# 45. Files the runner writes in the queue are 0600.
# 46. A queued job behind a held warm lock has hold "warm".
# 47. The dev, pre and full jobs in the load-file scenario all have hold null.
# 48. A dev job held by swap has hold "swap".
# 49. Once the warm-held and swap-held jobs start, hold is null.
# 50. With `classes = 3`, `budget = "x"` and `load_max = [1]`, jobs start on the default budget of 6;
#     a job file missing its keys is skipped and left as it was.
# 51. env kept in every state. A running run job keeps env, the submitter's environment as submitted.
# 52. a running slot job keeps its env, the {} that codeteam-slot wrote.
# 53. a run job whose tool cannot start is broken, with a reason and its env kept.
# 54. A running run job with no env is skipped by the runner and left byte-for-byte as it was written.
# 55. A done run job with no env is skipped and left byte-for-byte: the runner does not prune it.
# 56. A broken run job with no env is skipped and left byte-for-byte: the runner does not prune it.
# 57. A 400-digit integer budget in queue.toml does not stop the runner: exit 0, the queued job starts.
# 58. The same budget gives the heartbeat the default budget of 6; it has no load_max key.
# 59. A 400-digit guaranteed share for dev gives dev its default: at budget 1, one dev job runs and the second waits.
# 60. A run job whose child exits 0 with no fresh record is broken: "process gone without a fresh record".
# 61. A child whose log has the already-recorded line, and whose record is older than its start, is done: answered,
#     PASS from the record, no history line.
# 62. A child whose log has the restamp line, and whose record is fresh, is done: answered, PASS, no history line.
# 63. The runner makes no tmutil call, including the one that creates the queue folder (the stub's log stays empty).
# 64. Fifty finished job files and two queued dev jobs: one --once starts both queued jobs.
# The stub tmutil (below) records its argv in $tmp/tmutil.log; check 63 reads that log. No check reaches the real Time Machine.
set -u
# Stage 2 (v5.2) sets GROUP and CODETEAM_TEST_GROUP: children must not inherit them or their record keys change.
# export -n keeps the outer values available to this script without exporting them.
export -n GROUP CODETEAM_TEST_GROUP
here="$(cd "$(dirname "$0")/../.." && pwd)"
runner="$here/bin/codeteam-buildq"
py=python3
tmp="$(cd "$(mktemp -d)" && pwd -P)"
path="$tmp/stub:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

stage="scenarios running"
cleanup() {
  local rc=$? summary
  trap - EXIT
  pkill -f "$tmp/" 2>/dev/null
  "$py" -I "$tmp/lib.py" reap "$tmp" 2>/dev/null
  wait 2>/dev/null
  if [ -f "$tmp/summary" ]; then
    summary="$(cat "$tmp/summary")"
  else
    summary="buildq-sched: FAIL: no check summary ($stage, exit $rc)"
    rc=1
  fi
  rm -rf "$tmp"
  printf '%s\n' "$summary" >&2
  exit "$rc"
}
trap cleanup EXIT

cat > "$tmp/lib.py" <<'PY'
"""Helper for zone/tests/buildq-sched.sh: job files, snapshots of a queue, and the checks."""
import glob
import json
import os
import signal
import subprocess
import sys
import time

PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
S16 = ["ticket", "kind", "class", "key", "command", "worktree", "env", "team", "session", "submitted",
       "started", "finished", "pid", "state", "record", "cost", "estimated_start", "warm_lock", "test_flags",
       "tool", "record_mtime", "exit", "result", "reason", "fallback", "position"]
HEARTBEAT = ["pid", "beat", "budget", "used", "swap", "swap_max", "swap_hold"]
NO_LOAD = ["load", "load_max", "load_hold"]
SUBMITTED_ENV = {"PATH": PATH, "FOO": "bar"}
SNAP = ""
TM = ""


def write_json(path, obj):
    tmp = os.path.join(os.path.dirname(path), "." + os.path.basename(path) + ".tmp")
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def mode(path):
    return format(os.stat(path).st_mode & 0o777, "o")


def alive(pid):
    if not isinstance(pid, int):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def mkjobs(sc, body):
    """Writes run-job files for scenario folder sc from a JSON list; "sleep" is the stub's sleep, and "noenv" drops
    the job's env key."""
    q = os.path.join(sc, "run", "queue")
    os.makedirs(q, exist_ok=True)
    for spec in json.loads(body):
        t = spec["ticket"]
        sleep = spec.pop("sleep", 3)
        noenv = spec.pop("noenv", False)
        rec = os.path.join(sc, "records", t + ".json")
        job = {
            "ticket": t, "kind": "run", "class": "dev", "key": "k-" + t,
            "command": [str(sleep), os.path.join(sc, "marks", t), rec],
            "worktree": os.path.join(sc, "wt"), "env": dict(SUBMITTED_ENV),
            "team": "team-a", "session": "s1", "submitted": 1000,
            "started": None, "finished": None, "pid": None, "state": "queued",
            "record": rec, "cost": None, "estimated_start": None, "warm_lock": None,
            "test_flags": [], "tool": os.path.join(os.path.dirname(sc), "stub", "zone-tool"),
            "record_mtime": None, "exit": None, "result": None, "reason": None, "fallback": False,
        }
        job.update(spec)
        if noenv:
            del job["env"]
        write_json(os.path.join(q, t + ".json"), job)


def many(prefix, count, sleep, cls):
    return json.dumps([{"ticket": "%s%d" % (prefix, i), "class": cls, "team": "team-a",
                        "submitted": 1000 + i, "sleep": float(sleep)} for i in range(1, int(count) + 1)])


def donejobs(sc, count):
    """Writes count finished run jobs (F01, F02, ...) into scenario folder sc's queue, finished just now."""
    q = os.path.join(sc, "run", "queue")
    now = time.time()
    for i in range(1, int(count) + 1):
        t = "F%02d" % i
        write_json(os.path.join(q, t + ".json"), {
            "ticket": t, "kind": "run", "class": "dev", "key": "k-" + t, "command": ["x"], "worktree": sc,
            "team": "team-a", "submitted": now - 100, "started": now - 90, "finished": now, "pid": None,
            "state": "done", "exit": 0, "result": "PASS", "record": None, "reason": None, "fallback": False,
        })


def tm_lines():
    """The argv lines the stub tmutil has recorded, one per call."""
    try:
        with open(TM) as f:
            return f.read().splitlines()
    except OSError:
        return []


def snap(name, sc, extra):
    """Writes the queue as the runner left it: jobs, file modes, heartbeat, markers, liveness of job pids."""
    q = os.path.join(sc, "run", "queue")
    out = {"now": time.time(), "q_exists": os.path.isdir(q),
           "hb": read_json(os.path.join(sc, "run", "queue-runner.json")),
           "hb_in_queue": os.path.exists(os.path.join(q, "queue-runner.json"))}
    if out["q_exists"]:
        names = sorted(os.listdir(q))
        out["q_mode"] = mode(q)
        out["files"] = {n: mode(os.path.join(q, n)) for n in names if os.path.isfile(os.path.join(q, n))}
        jobs = {}
        for n in names:
            if n.startswith(".") or not n.endswith(".json"):
                continue
            body = read_json(os.path.join(q, n))
            jobs[n[:-5]] = body if body is not None else {"unreadable": n}
        out["jobs"] = jobs
    marks = {}
    md = os.path.join(sc, "marks")
    for t in (os.listdir(md) if os.path.isdir(md) else []):
        with open(os.path.join(md, t)) as f:
            marks[t] = f.read().splitlines()
    out["marks"] = marks
    hist = os.path.join(sc, "run", "queue-history.jsonl")
    out["history"] = [json.loads(line) for line in open(hist)] if os.path.exists(hist) else []
    out["alive"] = {t: alive(j.get("pid")) for t, j in out.get("jobs", {}).items()}
    out.update(dict(kv.split("=", 1) for kv in extra))
    dest = os.path.join(os.path.dirname(sc), "snap")
    os.makedirs(dest, exist_ok=True)
    write_json(os.path.join(dest, name + ".json"), out)


def reap(root):
    """Stops any runner under root whose heartbeat still names a live codeteam-buildq process."""
    for hb in glob.glob(os.path.join(root, "**", "queue-runner.json"), recursive=True):
        pid = (read_json(hb) or {}).get("pid")
        if alive(pid):
            cmd = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True).stdout
            if "codeteam-buildq" in cmd:
                os.kill(pid, signal.SIGTERM)


def S(name):
    with open(os.path.join(SNAP, name + ".json")) as f:
        return json.load(f)


def need(cond, msg):
    if not cond:
        raise AssertionError(msg)


def job(s, t):
    return s["jobs"][t]


def running(s):
    return sorted(t for t, j in s["jobs"].items() if j.get("state") == "running")


def marker(s, t):
    lines = s["marks"].get(t, [])
    return dict(tok.split("=", 1) for tok in lines[0].split() if "=" in tok) if lines else {}


def c01():
    j = job(S("basic"), "T1")
    missing = [k for k in S16 if k not in j]
    need(not missing, "missing " + ", ".join(missing))
    need(j["env"] == SUBMITTED_ENV, "env %r" % j["env"])


def c02():
    j = job(S("basic"), "T1")
    need(j.get("state") == "done", "state %r" % j.get("state"))
    need(j.get("exit") == 0 and j.get("result") == "PASS", "exit %r result %r" % (j.get("exit"), j.get("result")))
    need(j.get("record_mtime") is None, "record_mtime %r" % j.get("record_mtime"))


def c03():
    n = len(S("basic")["marks"].get("T1", []))
    need(n == 1, "%d marker lines" % n)


def c04():
    s = S("basic")
    need(not [n for n in s["files"] if n.endswith(".tmp")], "a temporary file is left")
    need(not [t for t, j in s["jobs"].items() if "unreadable" in j], "a job file does not parse")
    need(job(s, "T1").get("started") is not None, "the runner has not written T1")


def c05():
    m = marker(S("basic"), "T1")
    need(m.get("held") == "1" and m.get("ticket") == "T1" and m.get("foo") == "bar", "child saw %r" % m)


def c06():
    m = marker(S("basic"), "T1")
    need(m.get("nice") == "10", "nice %r" % m.get("nice"))


def c07():
    s = S("basic")
    need(marker(s, "T1").get("pid") == str(job(s, "T1").get("pid")), "child pid %r, job pid %r"
         % (marker(s, "T1").get("pid"), job(s, "T1").get("pid")))


def c08():
    s = S("basic")
    want = os.path.realpath(job(s, "T1")["worktree"])
    need(marker(s, "T1").get("cwd") == want, "child cwd %r, want %r" % (marker(s, "T1").get("cwd"), want))


def c09():
    s = S("basic")
    hb = s["hb"]
    need(isinstance(hb, dict), "no queue-runner.json beside the queue")
    missing = [k for k in HEARTBEAT if k not in hb]
    need(not missing, "heartbeat lacks " + ", ".join(missing))
    extra = [k for k in NO_LOAD if k in hb]
    need(not extra, "heartbeat has " + ", ".join(extra))
    need(not s["hb_in_queue"], "the heartbeat is inside the queue")
    need(abs(s["now"] - hb["beat"]) < 60, "beat %r is not current" % hb["beat"])


def c10():
    j = job(S("basic"), "T1")
    need("position" in j and j["position"] is None, "position %r after it finished" % j.get("position"))


def c11():
    s = S("order-2")
    need(job(s, "P1")["state"] == "running" and job(s, "D2")["state"] == "queued",
         "P1 %r, D2 %r" % (job(s, "P1")["state"], job(s, "D2")["state"]))


def c12():
    s = S("order-final")
    need(job(s, "P1")["started"] < job(s, "D2")["started"],
         "P1 started %r, D2 started %r" % (job(s, "P1")["started"], job(s, "D2")["started"]))


def c13():
    s = S("order-final")
    need(job(s, "P1")["started"] <= job(s, "D1")["finished"],
         "P1 started %r after D1 finished %r" % (job(s, "P1")["started"], job(s, "D1")["finished"]))


def c14():
    s = S("order-final")
    need(job(s, "D2")["started"] >= job(s, "D1")["finished"],
         "D2 started %r before D1 finished %r" % (job(s, "D2")["started"], job(s, "D1")["finished"]))


def c15():
    s = S("full-1")
    need(running(s) == ["D1", "D2"] and job(s, "D3")["state"] == "queued",
         "running %r, D3 %r" % (running(s), job(s, "D3")["state"]))


def c16():
    s = S("full-final")
    first = min(job(s, "D1")["finished"], job(s, "D2")["finished"])
    need(job(s, "F1")["started"] <= first, "F1 started %r, first dev finish %r" % (job(s, "F1")["started"], first))


def c17():
    s = S("full-final")
    need(job(s, "D3")["started"] > job(s, "F1")["started"],
         "D3 started %r, F1 started %r" % (job(s, "D3")["started"], job(s, "F1")["started"]))


def c18():
    s = S("six")
    need(len(running(s)) == 6, "running %r" % running(s))


def c19():
    s = S("ceiling")
    posts = [t for t in running(s) if t.startswith("P")]
    need(len(posts) == 2 and job(s, "P3")["state"] == "queued", "running %r, P3 %r" % (posts, job(s, "P3")["state"]))


def c20():
    s = S("budget_toml")
    need(len(running(s)) == 3, "running %r" % running(s))


def c21():
    s = S("budget_env")
    need(len(running(s)) == 2, "running %r" % running(s))


def c22():
    s = S("budget_default")
    need(len(running(s)) == 6, "running %r" % running(s))


def c23():
    s = S("rr-1")
    got = (job(s, "B1")["position"], job(s, "A2")["position"], job(s, "A3")["position"])
    need(got == (1, 2, 3), "positions B1, A2, A3 are %r" % (got,))


def c24():
    s = S("rr-final")
    order = sorted(s["jobs"], key=lambda t: job(s, t)["started"])
    need(order == ["A1", "B1", "A2", "A3"], "start order %r" % order)


def c25():
    s = S("cost-1")
    need(abs(job(s, "M1")["cost"] - 3.0) < 1e-9, "M1 cost %r" % job(s, "M1")["cost"])


def c26():
    s = S("cost-1")
    need(job(s, "L1")["cost"] == 1, "L1 cost %r" % job(s, "L1")["cost"])


def c27():
    s = S("cost-1")
    need(job(s, "H1")["cost"] == 6, "H1 cost %r" % job(s, "H1")["cost"])


def c28():
    s = S("cost-1")
    need(job(s, "S1")["cost"] == 2, "S1 cost %r" % job(s, "S1")["cost"])


def c29():
    s = S("cost-1")
    need(job(s, "N1")["cost"] == 1, "N1 cost %r" % job(s, "N1")["cost"])


def c30():
    s = S("cost-1")
    need(job(s, "F1")["cost"] == 4, "F1 cost %r" % job(s, "F1")["cost"])


def c31():
    s = S("est-1")
    j = job(s, "E2")
    need(j["state"] == "queued" and j.get("position") == 1 and j["estimated_start"] is None,
         "state %r, position %r, estimated_start %r" % (j["state"], j.get("position"), j["estimated_start"]))


def c32():
    s = S("est-2")
    want = job(s, "E1")["started"] + 5
    got = job(s, "E2")["estimated_start"]
    need(got is not None and abs(got - want) <= 0.5, "estimated_start %r, want about %r" % (got, want))


def started_under_load(t):
    j = job(S("load"), t)
    need(j["state"] == "running", "%s %r, hold %r" % (t, j["state"], j.get("hold")))


def c33():
    started_under_load("D1")


def c34():
    started_under_load("P1")


def c35():
    started_under_load("F1")


def c36():
    s = S("swap-1")
    need(job(s, "D1")["state"] == "queued" and s["hb"]["swap_hold"] is True,
         "D1 %r, swap_hold %r" % (job(s, "D1")["state"], s["hb"]["swap_hold"]))


def c37():
    s = S("swap-2")
    need(job(s, "D1")["state"] == "running" and s["hb"]["swap_hold"] is False,
         "D1 %r, swap_hold %r" % (job(s, "D1")["state"], s["hb"]["swap_hold"]))


def c38():
    s = S("warm-1")
    need(s["warm_ready"] == "0", "warm.ready did not appear before the readiness deadline")
    j = job(s, "W1")
    need(s["hb"] is not None and j["state"] == "queued" and j.get("position") == 1,
         "runner %r, W1 %r at position %r" % (s["hb"] is not None, j["state"], j.get("position")))


def c39():
    s = S("warm-2")
    need(job(s, "W1")["state"] == "running", "W1 %r" % job(s, "W1")["state"])


def c40():
    s = S("one-b")
    need(s["brc"] == "0" and s["bout"].strip() == "", "exit %r, output %r" % (s["brc"], s["bout"]))


def c41():
    s = S("one-b")
    need(s["ready"] == "beat", "first runner readiness outcome: %s" % s["ready"])
    need(s["hb"] is not None and s["hb"]["pid"] == int(s["apid"]),
         "heartbeat pid %r, first runner %r" % (s["hb"] and s["hb"].get("pid"), s["apid"]))


def c42():
    s = S("one-s1")
    need(s["ready"] == "beat", "first runner readiness outcome: %s" % s["ready"])
    need(s["salive"] == "yes" and s["hb"]["pid"] == int(s["apid"]),
         "standby alive %r, heartbeat pid %r" % (s["salive"], s["hb"] and s["hb"].get("pid")))


def c43():
    s = S("one-s2")
    need(s["takeover"] == "took_over", "standby readiness outcome: %s" % s["takeover"])
    need(s["hb"] is not None and s["hb"]["pid"] == int(s["spid"]),
         "heartbeat pid %r, standby %r" % (s["hb"] and s["hb"].get("pid"), s["spid"]))


def c44():
    s = S("mode-1")
    need(s.get("q_mode") == "700", "queue folder mode %r" % s.get("q_mode"))


def c45():
    s = S("mode-2")
    bad = {n: m for n, m in s["files"].items() if m != "600"}
    need(not bad and "M1.json" in s["files"], "modes %r" % bad)


def c46():
    j = job(S("warm-1"), "W1")
    need(j.get("hold") == "warm", "W1 hold %r" % j.get("hold"))


def c47():
    s = S("load")
    holds = {t: job(s, t).get("hold", "absent") for t in ("D1", "P1", "F1")}
    need(all(h is None for h in holds.values()), "holds %r" % holds)


def c48():
    j = job(S("swap-1"), "D1")
    need(j.get("hold") == "swap", "D1 hold %r" % j.get("hold"))


def c49():
    held = [job(S("warm-2"), "W1"), job(S("swap-2"), "D1")]
    need(all("hold" in j and j["hold"] is None for j in held), "holds after the start %r" % [j.get("hold") for j in held])


def c50():
    s = S("cfg")
    need(len(running(s)) == 6 and s["hb"]["budget"] == 6, "running %r, budget %r" % (running(s), s["hb"]["budget"]))
    need(job(s, "BAD") == {"ticket": "BAD"}, "the malformed job file became %r" % job(s, "BAD"))


def c51():
    j = job(S("env"), "R")
    need(j["state"] == "running" and j.get("env", "absent") == SUBMITTED_ENV,
         "state %r, env %r" % (j["state"], j.get("env", "absent")))


def c52():
    j = job(S("env"), "S")
    need(j["state"] == "running" and j.get("env", "absent") == {},
         "state %r, env %r" % (j["state"], j.get("env", "absent")))


def c53():
    j = job(S("env"), "B")
    need(j["state"] == "broken" and j.get("env", "absent") == SUBMITTED_ENV
         and isinstance(j.get("reason"), str) and j["reason"],
         "state %r, env %r, reason %r" % (j["state"], j.get("env", "absent"), j.get("reason")))


def untouched(t):
    """Job file t of the noenv scenario is byte-for-byte as written, and the runner ran (it wrote its heartbeat)."""
    need(S("noenv")["hb"] is not None, "the runner wrote no heartbeat")
    sc = os.path.join(os.path.dirname(SNAP), "noenv")
    with open(os.path.join(sc, "before", t + ".json"), "rb") as f:
        before = f.read()
    try:
        with open(os.path.join(sc, "run", "queue", t + ".json"), "rb") as f:
            after = f.read()
    except OSError:
        after = None
    need(after == before, "%s.json was %s" % (t, "removed" if after is None else "changed"))


def c54():
    untouched("NR")


def c55():
    untouched("ND")


def c56():
    untouched("NB")


def c57():
    s = S("bigbudget")
    need(s["brc"] == "0", "runner exit %r" % s["brc"])
    need(isinstance(s["hb"], dict), "no queue-runner.json beside the queue")
    need(running(s) == ["D1"], "running %r" % running(s))


def c58():
    hb = S("bigbudget")["hb"]
    need(isinstance(hb, dict) and hb.get("budget") == 6 and "load_max" not in hb, "heartbeat %r" % (hb,))


def c59():
    s = S("bigclass")
    need(s["brc"] == "0", "runner exit %r" % s["brc"])
    need(running(s) == ["D1"], "running %r, D2 %r" % (running(s), job(s, "D2")["state"]))


def c60():
    j = job(S("settle"), "SIL")
    need(j["state"] == "broken" and "process gone without a fresh record" in (j.get("reason") or ""),
         "state %r, reason %r" % (j["state"], j.get("reason")))


def answered_from_record(s, t):
    j = job(s, t)
    need(j["state"] == "done" and j.get("answered") is True and j.get("result") == "PASS" and j.get("exit") == 0,
         "state %r, answered %r, result %r, exit %r" % (j["state"], j.get("answered"), j.get("result"), j.get("exit")))
    hist = [h for h in s["history"] if h.get("hkey") == "k-" + t]
    need(not hist, "a history line was written: %r" % hist)


def c61():
    answered_from_record(S("settle"), "ANS")


def c62():
    answered_from_record(S("settle"), "RST")


def c63():
    need(S("mode-1")["q_exists"] is True, "the runner did not create the queue folder")
    need(not tm_lines(), "tmutil was called: %r" % tm_lines())


def c64():
    s = S("done50")
    done = [t for t, j in s["jobs"].items() if j.get("state") == "done"]
    need(running(s) == ["Q1", "Q2"] and len(done) == 50, "running %r, done %d" % (running(s), len(done)))


CHECKS = [
    (1, "a finished run job has every job-file field, env included, and env as submitted", c01),
    (2, "a finished run job reads done, exit 0, result PASS from its record; no record at its start", c02),
    (3, "the job's command runs once: one marker line", c03),
    (4, "no temporary job file is left and every job file parses", c04),
    (5, "the child sees CODETEAM_SLOT_HELD=1, CODETEAM_BUILDQ_TICKET and the submitter's environment", c05),
    (6, "the child of a dev job runs at nice 10", c06),
    (7, "the child's pid is the job's pid", c07),
    (8, "the child's working directory is the job's worktree", c08),
    (9, "queue-runner.json is the heartbeat beside the queue, with its fields and a current beat", c09),
    (10, "a finished job has position null", c10),
    (11, "budget 1: a post job starts while a newer dev job waits", c11),
    (12, "the post job starts before the newer dev job", c12),
    (13, "the post job starts no later than the first dev job's finish", c13),
    (14, "the newer dev job starts after the first dev job finishes (the budget)", c14),
    (15, "budget 2: two dev jobs run at once", c15),
    (16, "a full job starts no later than the next dev finish", c16),
    (17, "a dev job queued behind the full job starts after it", c17),
    (18, "budget 6: six dev jobs run at once (dev has no ceiling)", c18),
    (19, "post ceiling 2: two post jobs run, the third waits", c19),
    (20, "queue.toml's budget beats CODETEAM_BUILD_BUDGET", c20),
    (21, "CODETEAM_BUILD_BUDGET is the budget when queue.toml has none", c21),
    (22, "the budget is 6 when neither is set", c22),
    (23, "round-robin: after a team-a start, the team-b job is next (positions 1, 2, 3)", c23),
    (24, "round-robin: the starts run a1, b1, a2, a3", c24),
    (25, "cost is the median of the last 5 cpu/wall ratios (3.0)", c25),
    (26, "cost clamps up to 1 below a ratio of 1", c26),
    (27, "cost clamps down to the budget above it", c27),
    (28, "an empty key takes its history from the suite line (cost 2)", c28),
    (29, "a dev job with no record costs 1", c29),
    (30, "a full job with no record costs 4", c30),
    (31, "a queued job with no history has a null estimated_start", c31),
    (32, "a queued job's estimated_start is the running start plus its median wall", c32),
    (33, "load far over load_max never holds a dev start", c33),
    (34, "load far over load_max never holds a pre start", c34),
    (35, "load far over load_max never holds a full start", c35),
    (36, "swap over swap_max holds a dev start", c36),
    (37, "when swap drops, the held dev job starts", c37),
    (38, "a warm lock held by flock holds its job", c38),
    (39, "when the warm lock is released, its job starts", c39),
    (40, "a second runner exits 0 at once, silently", c40),
    (41, "the second runner leaves the first runner's heartbeat", c41),
    (42, "--standby waits while another runner holds the queue", c42),
    (43, "--standby takes over when the runner holding the queue dies", c43),
    (44, "the runner creates the queue folder 0700", c44),
    (45, "files the runner writes in the queue are 0600", c45),
    (46, "a queued job behind a held warm lock has hold warm", c46),
    (47, "no job is held by load: dev, pre and full started under load have hold null", c47),
    (48, "a dev job held by swap has hold swap", c48),
    (49, "hold is null once the job starts", c49),
    (50, "a wrong-typed queue.toml gives defaults, load_max is ignored, and a job file missing its keys is skipped", c50),
    (51, "a running run job keeps env, as submitted", c51),
    (52, "a running slot job keeps its env ({})", c52),
    (53, "a run job whose tool cannot start is broken, with a reason and its env kept", c53),
    (54, "a running run job with no env is skipped and left byte-for-byte", c54),
    (55, "a done run job with no env is skipped and left byte-for-byte", c55),
    (56, "a broken run job with no env is skipped and left byte-for-byte", c56),
    (57, "a 400-digit budget does not stop the runner: exit 0, the queued job starts", c57),
    (58, "a 400-digit budget gives the heartbeat budget 6; load_max is ignored (not in the heartbeat)", c58),
    (59, "a 400-digit guaranteed share gives dev its default: one dev job starts at budget 1", c59),
    (60, "a child that exits 0 with no fresh record is broken: process gone without a fresh record", c60),
    (61, "a child answering from an older record is done: answered, PASS, no history line", c61),
    (62, "a child answering with a restamp is done: answered, PASS, no history line", c62),
    (63, "the runner makes no tmutil call, including the one that creates the queue folder", c63),
    (64, "fifty finished job files and two queued dev jobs: one --once starts both", c64),
]


def check(scenarios):
    root = os.path.dirname(SNAP)
    failed_scenarios = []
    for name in scenarios:
        try:
            with open(os.path.join(root, "status", name)) as f:
                rc = f.read().strip()
        except OSError:
            rc = ""
        if rc != "0":
            failure = "FAIL scenario %s: %s" % (name, "exit " + rc if rc else "no status")
            print(failure)
            failed_scenarios.append(failure)
    bad = []
    for num, label, fn in CHECKS:
        try:
            fn()
        except Exception as e:
            bad.append("%d %s" % (num, label))
            print("FAIL %d %s: %s: %s" % (num, label, type(e).__name__, e))
            continue
        print("ok   %d %s" % (num, label))
    summary = ("buildq-sched: %d of 64 checks failed: %s" % (len(bad), "; ".join(bad + failed_scenarios))
               if bad or failed_scenarios else "buildq-sched: all 64 checks ok")
    with open(os.path.join(root, "summary"), "w") as f:
        f.write(summary + "\n")
    return 1 if bad or failed_scenarios else 0


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "mkjobs":
        mkjobs(args[0], args[1])
    elif cmd == "many":
        print(many(*args))
    elif cmd == "snap":
        snap(args[0], args[1], args[2:])
    elif cmd == "done":
        donejobs(args[0], args[1])
    elif cmd == "reap":
        reap(args[0])
    elif cmd == "check":
        SNAP = args[0]
        TM = args[1]
        sys.exit(check(args[2:]))
PY

mkdir -p "$tmp/stub"
# Time Machine is never touched: a stub tmutil (first on PATH) records its argv in $tmp/tmutil.log and exits 0.
cat > "$tmp/stub/tmutil" <<SH
#!/bin/sh
printf '%s\n' "\$*" >> "$tmp/tmutil.log"
exit 0
SH
chmod +x "$tmp/stub/tmutil"
# Tools for the child-exit checks: one writes nothing, one answers from an older record, one restamps its record.
printf '#!/bin/sh\nexit 0\n' > "$tmp/stub/zone-silent"
printf '#!/bin/sh\necho "zone-test: PASS at 12:00 already recorded for this exact code; not run again"\nexit 0\n' \
  > "$tmp/stub/zone-answer-old"
cat > "$tmp/stub/zone-restamp" <<'SH'
#!/bin/sh
while [ $# -gt 0 ] && [ "$1" != "--" ]; do shift; done
[ $# -gt 0 ] && shift
echo "zone-test: PASS at 12:00 already recorded; nothing these tests touch has changed since; not run again"
printf '{"result": "PASS", "exit": 0, "cpu_seconds": 1, "seconds": 1}\n' > "$3"
exit 0
SH
chmod +x "$tmp/stub/zone-silent" "$tmp/stub/zone-answer-old" "$tmp/stub/zone-restamp"
# The job's tool: `test [flags] -- SECONDS MARK RECORD [EXIT]`. SECONDS=hold waits for the scenario's
# release/<ticket> file (0.05 s polls, 300 s safety cap). The start marker records the ticket, held flag, FOO,
# cwd, pid and nice; after the wait the tool writes its record and exits.
cat > "$tmp/stub/zone-tool" <<'SH'
#!/bin/sh
while [ $# -gt 0 ] && [ "$1" != "--" ]; do shift; done
[ $# -gt 0 ] && shift
secs=$1 mark=$2 rec=$3 code=${4:-0}
echo "ticket=${CODETEAM_BUILDQ_TICKET:-unset} held=${CODETEAM_SLOT_HELD:-unset} foo=${FOO:-unset} cwd=$(pwd -P) pid=$$ nice=$(ps -o nice= -p $$ | tr -d ' ')" >> "$mark"
c=
trap '[ -z "$c" ] || kill "$c" 2>/dev/null; exit 143' TERM INT
if [ "$secs" = hold ]; then
  release="${mark%/marks/*}/release/${mark##*/}"
  end=$(( $(date +%s) + 300 ))
  while [ ! -e "$release" ]; do
    [ "$(date +%s)" -lt "$end" ] || exit 124
    sleep 0.05 &
    c=$!
    wait "$c"
  done
else
  sleep "$secs" &
  c=$!
  wait "$c"
fi
result=PASS
[ "$code" = 0 ] || result=FAIL
printf '{"result": "%s", "exit": %s, "cpu_seconds": 0.5, "seconds": 1}\n' "$result" "$code" > "$rec"
exit "$code"
SH
chmod +x "$tmp/stub/zone-tool"

# rn SC ARGS: one runner on scenario SC's queue, under env -i. RUNENV holds extra VAR=VALUE words (a later
# word wins); EXEC=exec makes the runner replace the calling subshell, so $! is its pid; RUNWRAP wraps it.
rn() {
  local sc=$1
  shift
  ${RUNWRAP:-} ${EXEC:-} env -i PATH="$path" HOME="$tmp" CODETEAM_QUEUE_DIR="$sc/run/queue" \
    CODETEAM_BUILDQ_TICK=0.05 CODETEAM_BUILDQ_IDLE_EXIT=1 CODETEAM_BUILDQ_LOAD_FILE="$sc/load" \
    ${RUNENV:-} "$runner" "$@"
}
# Safety caps bound a stuck runner, not how quickly a scheduling decision must finish under load.
once() { RUNWRAP="/usr/bin/timeout 60" rn "$1" --once; }
loop() { RUNWRAP="/usr/bin/timeout 120" rn "$1"; }
# within SECS COMMAND...: retries COMMAND every 0.1 s until it succeeds or SECS have passed. The clock bounds it, not a
# count: a sleep on a loaded machine can take several times its argument.
within() {
  local end=$(( $(date +%s) + $1 ))
  shift
  while ! "$@"; do
    [ "$(date +%s)" -ge "$end" ] && return 1
    sleep 0.1
  done
}
# exited PID: PID is no longer running (a zombie child counts as exited).
exited() {
  case "$(ps -o stat= -p "$1" 2>/dev/null)" in
    ""|Z*) return 0 ;;
  esac
  return 1
}
# Stop polling on readiness or exit, keeping the outcome distinct for the snapshot's checks.
hb_or_exited() {
  if test -e "$1/run/queue-runner.json"; then
    ready=beat
  elif exited "$2"; then
    ready=exited
  else
    return 1
  fi
}
took_over() {
  if grep -Eq "\"pid\": *$2[^0-9]" "$1/run/queue-runner.json" 2>/dev/null; then
    takeover=took_over
  elif exited "$2"; then
    takeover=exited
  else
    return 1
  fi
}
pyl() { "$py" -I "$tmp/lib.py" "$@"; }
snap() { pyl snap "$@"; }
# newsc SC: a scenario folder with its worktree, marker and record folders, and a quiet load file.
newsc() {
  mkdir -p "$1/wt" "$1/marks" "$1/records" "$1/release" "$1/run/queue"
  printf '0.5\n0\n' > "$1/load"
}

sc_basic() {
  trap - EXIT
  local sc="$tmp/basic"
  newsc "$sc"
  pyl mkjobs "$sc" '[{"ticket":"T1","submitted":1000,"sleep":0.3}]'
  loop "$sc"
  snap basic "$sc"
}

sc_order() {
  trap - EXIT
  local sc="$tmp/order"
  newsc "$sc"
  pyl mkjobs "$sc" '[{"ticket":"D1","team":"team-a","submitted":1000,"sleep":"hold"}]'
  RUNENV="CODETEAM_BUILD_BUDGET=1" once "$sc"
  pyl mkjobs "$sc" '[{"ticket":"P1","class":"post","team":"team-b","submitted":1001,"sleep":0.2},{"ticket":"D2","team":"team-c","submitted":1002,"sleep":0.2}]'
  RUNENV="CODETEAM_BUILD_BUDGET=1" once "$sc"
  snap order-2 "$sc"
  touch "$sc/release/D1"
  RUNENV="CODETEAM_BUILD_BUDGET=1" loop "$sc"
  snap order-final "$sc"
}

sc_full() {
  trap - EXIT
  local sc="$tmp/full"
  newsc "$sc"
  pyl mkjobs "$sc" '[{"ticket":"D1","team":"team-a","submitted":1000,"sleep":"hold"},{"ticket":"D2","team":"team-a","submitted":1001,"sleep":"hold"},{"ticket":"D3","team":"team-a","submitted":1002,"sleep":0.2}]'
  RUNENV="CODETEAM_BUILD_BUDGET=2" once "$sc"
  snap full-1 "$sc"
  pyl mkjobs "$sc" '[{"ticket":"F1","class":"full","team":"team-b","submitted":1003,"sleep":0.3}]'
  RUNENV="CODETEAM_BUILD_BUDGET=2" once "$sc"
  snap full-2 "$sc"
  touch "$sc/release/D1" "$sc/release/D2"
  RUNENV="CODETEAM_BUILD_BUDGET=2" loop "$sc"
  snap full-final "$sc"
}

sc_six() {
  trap - EXIT
  local sc="$tmp/six"
  newsc "$sc"
  pyl mkjobs "$sc" "$(pyl many S 6 3 dev)"
  RUNENV="CODETEAM_BUILD_BUDGET=6" once "$sc"
  snap six "$sc"
}

sc_ceiling() {
  trap - EXIT
  local sc="$tmp/ceiling"
  newsc "$sc"
  printf '[classes.post]\nguaranteed = 1\nceiling = 2\n' > "$sc/run/queue.toml"
  pyl mkjobs "$sc" "$(pyl many P 3 3 post)"
  RUNENV="CODETEAM_BUILD_BUDGET=6" once "$sc"
  snap ceiling "$sc"
}

sc_budget_toml() {
  trap - EXIT
  local sc="$tmp/budget_toml"
  newsc "$sc"
  printf 'budget = 3\n' > "$sc/run/queue.toml"
  pyl mkjobs "$sc" "$(pyl many D 5 3 dev)"
  RUNENV="CODETEAM_BUILD_BUDGET=5" once "$sc"
  snap budget_toml "$sc"
}

sc_budget_env() {
  trap - EXIT
  local sc="$tmp/budget_env"
  newsc "$sc"
  pyl mkjobs "$sc" "$(pyl many D 4 3 dev)"
  RUNENV="CODETEAM_BUILD_BUDGET=2" once "$sc"
  snap budget_env "$sc"
}

sc_budget_default() {
  trap - EXIT
  local sc="$tmp/budget_default"
  newsc "$sc"
  pyl mkjobs "$sc" "$(pyl many D 7 3 dev)"
  once "$sc"
  snap budget_default "$sc"
}

sc_rr() {
  trap - EXIT
  local sc="$tmp/rr"
  newsc "$sc"
  pyl mkjobs "$sc" '[{"ticket":"A1","team":"team-a","submitted":1000,"sleep":1},{"ticket":"A2","team":"team-a","submitted":1001,"sleep":0.2},{"ticket":"A3","team":"team-a","submitted":1002,"sleep":0.2},{"ticket":"B1","team":"team-b","submitted":1003,"sleep":0.2}]'
  RUNENV="CODETEAM_BUILD_BUDGET=1" once "$sc"
  snap rr-1 "$sc"
  RUNENV="CODETEAM_BUILD_BUDGET=1" loop "$sc"
  snap rr-final "$sc"
}

sc_cost() {
  trap - EXIT
  local sc="$tmp/cost"
  newsc "$sc"
  local hist="$sc/run/queue-history.jsonl"
  # k-med: seven lines, ratios 5 6 1 2 3 4 5; the median of the last five is 3.
  for c in 50 60 10 20 30 40 50; do
    printf '{"hkey": "k-med", "class": "dev", "cpu_seconds": %s, "wall_seconds": 10, "finished": 1}\n' "$c" >> "$hist"
  done
  printf '%s\n' '{"hkey": "k-low", "class": "dev", "cpu_seconds": 2, "wall_seconds": 10, "finished": 1}' >> "$hist"
  printf '%s\n' '{"hkey": "k-high", "class": "dev", "cpu_seconds": 90, "wall_seconds": 10, "finished": 1}' >> "$hist"
  printf '{"hkey": "suite 0.1 %s %s", "class": "dev", "cpu_seconds": 20, "wall_seconds": 10, "finished": 1}\n' \
    "$sc/marks/S1" "$sc/records/S1.json" >> "$hist"
  pyl mkjobs "$sc" '[{"ticket":"M1","key":"k-med","submitted":1001},{"ticket":"L1","key":"k-low","submitted":1002},{"ticket":"H1","key":"k-high","submitted":1003},{"ticket":"S1","key":"","sleep":0.1,"submitted":1004},{"ticket":"N1","submitted":1005},{"ticket":"F1","class":"full","key":"k-fnone","submitted":1006}]'
  RUNENV="CODETEAM_BUILD_BUDGET=6" once "$sc"
  snap cost-1 "$sc"
}

sc_est() {
  trap - EXIT
  local sc="$tmp/est"
  newsc "$sc"
  pyl mkjobs "$sc" '[{"ticket":"E1","key":"k-est1","submitted":1000,"sleep":"hold"},{"ticket":"E2","key":"k-est2","submitted":1001}]'
  RUNENV="CODETEAM_BUILD_BUDGET=1" once "$sc"
  snap est-1 "$sc"
  printf '%s\n' '{"hkey": "k-est1", "class": "dev", "cpu_seconds": 5, "wall_seconds": 5, "finished": 1}' >> "$sc/run/queue-history.jsonl"
  RUNENV="CODETEAM_BUILD_BUDGET=1" once "$sc"
  snap est-2 "$sc"
}

sc_load() {
  trap - EXIT
  local sc="$tmp/load"
  newsc "$sc"
  # The first word is ignored and swap is 0; the scenario also gives the jobs room in the budget.
  printf 'load_max = 10\n' > "$sc/run/queue.toml"
  printf '500\n0\n' > "$sc/load"
  pyl mkjobs "$sc" '[{"ticket":"D1","submitted":1000},{"ticket":"P1","class":"pre","team":"team-b","submitted":1001},{"ticket":"F1","class":"full","team":"team-c","submitted":1002}]'
  RUNENV="CODETEAM_BUILD_BUDGET=6" once "$sc"
  snap load "$sc"
}

sc_swap() {
  trap - EXIT
  local sc="$tmp/swap"
  newsc "$sc"
  printf 'swap_max = 0.9\n' > "$sc/run/queue.toml"
  printf '1\n0.95\n' > "$sc/load"
  pyl mkjobs "$sc" '[{"ticket":"D1","submitted":1000}]'
  RUNENV="CODETEAM_BUILD_BUDGET=6" once "$sc"
  snap swap-1 "$sc"
  printf '1\n0.1\n' > "$sc/load"
  RUNENV="CODETEAM_BUILD_BUDGET=6" once "$sc"
  snap swap-2 "$sc"
}

sc_warm() {
  trap - EXIT
  local sc="$tmp/warm" lock
  newsc "$sc"
  lock="$sc/warm.lock"
  pyl mkjobs "$sc" "[{\"ticket\":\"W1\",\"submitted\":1000,\"warm_lock\":\"$lock\"}]"
  "$py" -I -c 'import fcntl, os, sys, time
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)
fcntl.flock(fd, fcntl.LOCK_EX)
open(sys.argv[2], "w").close()
time.sleep(600)' "$lock" "$sc/warm.ready" >/dev/null 2>&1 &
  local hold=$!
  within 30 test -e "$sc/warm.ready"
  local warm_ready=$?
  once "$sc"
  snap warm-1 "$sc" warm_ready="$warm_ready"
  kill "$hold" 2>/dev/null || :
  wait "$hold" 2>/dev/null || :
  once "$sc"
  snap warm-2 "$sc"
}

sc_one() {
  trap - EXIT
  local sc="$tmp/one" a s out brc ready=timeout takeover=timeout
  newsc "$sc"
  ( EXEC=exec RUNENV="CODETEAM_BUILDQ_IDLE_EXIT=0" rn "$sc" >/dev/null 2>&1 ) &
  a=$!
  within 30 hb_or_exited "$sc" "$a"
  out="$(RUNWRAP="/usr/bin/timeout 30" rn "$sc" 2>&1)"
  brc=$?
  snap one-b "$sc" brc="$brc" bout="$out" apid="$a" ready="$ready"
  ( EXEC=exec RUNENV="CODETEAM_BUILDQ_IDLE_EXIT=1" rn "$sc" --standby >/dev/null 2>&1 ) &
  s=$!
  # Negative window: standby must not exit; slowness cannot fail it. This alone does not prove it reached the lock.
  sleep 0.3
  snap one-s1 "$sc" apid="$a" spid="$s" ready="$ready" salive="$(kill -0 "$s" 2>/dev/null && echo yes || echo no)"
  kill -9 "$a" 2>/dev/null || :
  wait "$a" 2>/dev/null || :
  within 30 took_over "$sc" "$s"
  snap one-s2 "$sc" spid="$s" takeover="$takeover"
  kill "$s" 2>/dev/null || :
}

sc_mode() {
  trap - EXIT
  local sc="$tmp/mode"
  mkdir -p "$sc/wt" "$sc/marks" "$sc/records" "$sc/run"
  printf '0.5\n0\n' > "$sc/load"
  once "$sc"
  snap mode-1 "$sc"
  pyl mkjobs "$sc" '[{"ticket":"M1","submitted":1000,"sleep":0.2}]'
  loop "$sc"
  snap mode-2 "$sc"
}

sc_cfg() {
  trap - EXIT
  local sc="$tmp/cfg"
  newsc "$sc"
  printf 'classes = 3\nbudget = "x"\nload_max = [1]\n' > "$sc/run/queue.toml"
  pyl mkjobs "$sc" "$(pyl many D 7 3 dev)"
  printf '{"ticket": "BAD"}' > "$sc/run/queue/BAD.json"
  once "$sc"
  snap cfg "$sc"
}

sc_env() {
  trap - EXIT
  local sc="$tmp/env" live
  newsc "$sc"
  # Keep the slot alive across the decision; the scratch argument also lets cleanup find it on failure.
  "$py" -I -c 'import time; time.sleep(600)' "$sc/slot" >/dev/null 2>&1 &
  live=$!
  pyl mkjobs "$sc" "[{\"ticket\":\"R\",\"submitted\":1000,\"sleep\":3},{\"ticket\":\"B\",\"submitted\":1001,\"tool\":\"$sc/nonexistent\"},{\"ticket\":\"S\",\"kind\":\"slot\",\"tool\":\"cargo\",\"command\":[\"cargo\",\"build\"],\"key\":\"slot cargo\",\"record\":null,\"env\":{},\"submitted\":1002,\"pid\":$live}]"
  once "$sc"
  snap env "$sc"
  kill "$live" 2>/dev/null || :
  wait "$live" 2>/dev/null || :
}

sc_settle() {
  trap - EXIT
  local sc="$tmp/settle"
  newsc "$sc"
  printf '{"result": "PASS", "exit": 0, "cpu_seconds": 1, "seconds": 1}\n' > "$sc/records/ANS.json"
  printf '{"result": "PASS", "exit": 0, "cpu_seconds": 1, "seconds": 1}\n' > "$sc/records/RST.json"
  pyl mkjobs "$sc" "[{\"ticket\":\"SIL\",\"tool\":\"$tmp/stub/zone-silent\",\"submitted\":1000},{\"ticket\":\"ANS\",\"tool\":\"$tmp/stub/zone-answer-old\",\"submitted\":1001},{\"ticket\":\"RST\",\"tool\":\"$tmp/stub/zone-restamp\",\"submitted\":1002}]"
  loop "$sc"
  snap settle "$sc"
}

sc_noenv() {
  trap - EXIT
  local sc="$tmp/noenv" t
  newsc "$sc"
  mkdir -p "$sc/before"
  printf 'retention_hours = 1\n' > "$sc/run/queue.toml"
  pyl mkjobs "$sc" '[{"ticket":"NR","state":"running","pid":null,"started":900,"submitted":800,"noenv":true},{"ticket":"ND","state":"done","exit":0,"result":"PASS","started":1,"finished":1,"submitted":1,"noenv":true},{"ticket":"NB","state":"broken","reason":"x","started":1,"finished":1,"submitted":1,"noenv":true}]'
  for t in NR ND NB; do cp "$sc/run/queue/$t.json" "$sc/before/$t.json"; done
  once "$sc"
  snap noenv "$sc"
}

sc_bigbudget() {
  trap - EXIT
  local sc="$tmp/bigbudget" brc
  newsc "$sc"
  printf 'budget = 1%s\nload_max = 10\n' "$(printf '%0399d' 0)" > "$sc/run/queue.toml"
  pyl mkjobs "$sc" "$(pyl many D 1 3 dev)"
  once "$sc"
  brc=$?
  snap bigbudget "$sc" brc="$brc"
}

sc_bigclass() {
  trap - EXIT
  local sc="$tmp/bigclass" brc
  newsc "$sc"
  printf '[classes.dev]\nguaranteed = 1%s\n' "$(printf '%0399d' 0)" > "$sc/run/queue.toml"
  pyl mkjobs "$sc" "$(pyl many D 2 3 dev)"
  RUNENV="CODETEAM_BUILD_BUDGET=1" once "$sc"
  brc=$?
  snap bigclass "$sc" brc="$brc"
}

sc_done50() {
  trap - EXIT
  local sc="$tmp/done50"
  newsc "$sc"
  pyl done "$sc" 50
  pyl mkjobs "$sc" '[{"ticket":"Q1","team":"team-a","submitted":1000,"sleep":3},{"ticket":"Q2","team":"team-b","submitted":1001,"sleep":3}]'
  once "$sc"
  snap done50 "$sc"
}

# ERR inheritance keeps a failed intermediate step (including a command substitution) from being masked by
# a later successful snapshot. Expected failures, such as waiting for a killed child, are explicitly ignored.
run_scenario() {
  trap - EXIT
  local scenario=$1 rc
  set -E
  trap 'printf "%s\n" "$?" > "$tmp/status/$scenario.failed"' ERR
  "$scenario"
  rc=$?
  trap - ERR
  if [ -f "$tmp/status/$scenario.failed" ]; then
    read -r rc < "$tmp/status/$scenario.failed"
  fi
  printf '%s\n' "$rc" > "$tmp/status/$scenario"
  return "$rc"
}

scenarios=(sc_basic sc_order sc_cfg sc_full sc_six sc_ceiling sc_budget_toml sc_budget_env
           sc_budget_default sc_rr sc_cost sc_est sc_load sc_swap sc_warm sc_one sc_mode sc_env
           sc_settle sc_noenv sc_bigbudget sc_bigclass sc_done50)
pids=()
mkdir -p "$tmp/status"
for scenario in "${scenarios[@]}"; do
  run_scenario "$scenario" &
  pids+=("$!")
done
for pid in "${pids[@]}"; do
  wait "$pid" || :
done

stage=checking
pyl check "$tmp/snap" "$tmp/tmutil.log" "${scenarios[@]}"
exit $?
