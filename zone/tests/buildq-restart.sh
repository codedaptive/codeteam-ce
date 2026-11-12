#!/bin/bash
# Nine parallel scenarios cover restart, settlement and pruning, using scratch processes and queues.
# zone/tests/buildq-restart.sh: the runner can die and come back, and it settles every job it finds from the files
# alone (the reconcile step). Each scenario is a folder
# under a scratch dir with its own queue. Running jobs are stub zone-tools (see buildq-sched.sh); a pid the scenario
# needs dead is one that has exited and been reaped, and a live one is a stub that keeps its tool name on its command
# line. The scenarios run side by side; then one checker reads the snapshots. Nothing here reads the live codeteam checkout:
# every runner runs under env -i with CODETEAM_QUEUE_DIR set to its scratch queue. BUILDQ_RESTART_PS_DELAY
# delays only the runners' ps calls for load-race reproduction. Snapshots record safety-bound outcomes, checked
# before job assertions; the EXIT trap prints a check summary on stderr.
#  1. A runner killed mid-queue leaves its held job alive; the restart adopts it before release, and it finishes
#     done with its record (PASS, exit 0), with the same pid.
#  2. The queued jobs run after the restart.
#  3. Each job's marker appears exactly once: no job runs twice.
#  4. A running job with pid null is broken (the runner died between marking and spawning).
#  5. A broken job with pid null is not started, and stays broken, on a later decision.
#  6. A running job whose pid is gone without a record is broken.
#  7. A running job whose pid is gone, with a record newer than its record_mtime, is done with the record's result and exit.
#  8. A running job whose pid is gone, with a record older than its record_mtime, is broken.
# 10. A queued slot job whose pid is gone is broken.
# 11. A queued slot job whose pid is alive is not broken.
# 12. A running slot job whose pid is gone is done, with exit null.
# 13. A finished job older than retention_hours is pruned, with its log.
# 14. A finished job younger than retention_hours is kept, with its log.
# 19. An adopted running job whose pid is gone without a record is broken: "process gone without a fresh record".
# 20. An adopted job whose log has the already-recorded line, and whose record is older than record_mtime, is done:
#     answered, PASS from the record, no history line.
# 21. An adopted job whose log has the restamp line, and whose record is fresh, is done: answered, no history line.
# 22. env kept in every state. An adopted running job keeps its env, as submitted, after the restarted
#     runner's first decision.
# 23. An adopted job whose log has the already-recorded line only after other output (not zone-tool's own first
#     line), with an older PASS record, is broken: process gone without a fresh record, not answered.
# 24. An adopted job whose log has --single's wait line first and the already-recorded line second, with an older
#     PASS record, is done: answered, PASS, no history line.
# 25. an adopted job that then finishes keeps the env it was submitted with.
# Time Machine is never touched: a stub tmutil (first on PATH) stands in for it, as in buildq-sched.sh.
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
    summary="buildq-restart: FAIL: no check summary ($stage, exit $rc)"
    rc=1
  fi
  rm -rf "$tmp"
  printf '%s\n' "$summary" >&2
  exit "$rc"
}
trap cleanup EXIT

cat > "$tmp/lib.py" <<'PY'
"""Helper for zone/tests/buildq-restart.sh: job files, snapshots of a queue, and the checks."""
import glob
import json
import os
import signal
import subprocess
import sys
import time

PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
SUBMITTED_ENV = {"PATH": PATH, "FOO": "bar"}
SNAP = ""


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
    """Writes run-job files; "sleep" is a duration or "hold" until release/<ticket> exists."""
    q = os.path.join(sc, "run", "queue")
    os.makedirs(q, exist_ok=True)
    for spec in json.loads(body):
        t = spec["ticket"]
        sleep = spec.pop("sleep", 3)
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
        if sleep == "hold":
            job["command"].append(os.path.join(sc, "release", t))
        job.update(spec)
        write_json(os.path.join(q, t + ".json"), job)


def snap(name, sc, extra):
    """Writes the queue as the runner left it: jobs, file modes, heartbeat, markers, liveness of job pids."""
    q = os.path.join(sc, "run", "queue")
    out = {"now": time.time(), "q_exists": os.path.isdir(q),
           "hb": read_json(os.path.join(sc, "run", "queue-runner.json"))}
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
            cmd = subprocess.run(["/bin/ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True).stdout
            if "codeteam-buildq" in cmd:
                os.kill(pid, signal.SIGTERM)


def S(name):
    with open(os.path.join(SNAP, name + ".json")) as f:
        s = json.load(f)
    scenario = name.split("-")[0]
    if "runner_rc" in s:
        rc = s["runner_rc"]
        need(rc == "0", "%s's %s runner %s (exit %s) before deciding" %
             (scenario, s["runner_mode"], "timed out" if rc == "124" else "failed", rc))
    for bound, outcome in s.items():
        if bound.endswith("_wait"):
            need(outcome == "ok", "%s's %s bound timed out before its event" % (scenario, bound))
    return s


def need(cond, msg):
    if not cond:
        raise AssertionError(msg)


def job(s, t):
    return s["jobs"][t]


def c01():
    s = S("r1-end")
    j = job(s, "J1")
    k = job(S("r1-killed"), "J1")
    need(j["state"] == "done" and j["exit"] == 0 and j["result"] == "PASS",
         "state %r exit %r result %r" % (j["state"], j["exit"], j["result"]))
    need(j["pid"] == k["pid"], "pid %r before the restart, %r after" % (k["pid"], j["pid"]))
    need(os.path.exists(j["record"]), "no record at %r" % j["record"])


def c02():
    s = S("r1-end")
    need(job(s, "J2")["state"] == "done" and job(s, "J3")["state"] == "done",
         "J2 %r, J3 %r" % (job(s, "J2")["state"], job(s, "J3")["state"]))


def c03():
    s = S("r1-end")
    counts = {t: len(s["marks"].get(t, [])) for t in ("J1", "J2", "J3")}
    need(all(n == 1 for n in counts.values()), "marker lines %r" % counts)


def c04():
    s = S("r2-1")
    j = job(s, "NP")
    need(j["state"] == "broken" and isinstance(j["reason"], str) and j["reason"],
         "state %r reason %r" % (j["state"], j["reason"]))
    need(not s["marks"].get("NP"), "the job was started: %r" % s["marks"].get("NP"))


def c05():
    s = S("r2-2")
    need(job(s, "NP")["state"] == "broken" and not s["marks"].get("NP"),
         "state %r, marker %r" % (job(s, "NP")["state"], s["marks"].get("NP")))


def c06():
    j = job(S("r3"), "G1")
    need(j["state"] == "broken" and isinstance(j["reason"], str) and j["reason"],
         "state %r reason %r" % (j["state"], j["reason"]))


def c07():
    j = job(S("r4"), "FR")
    need(j["state"] == "done" and j["result"] == "FAIL" and j["exit"] == 1,
         "state %r result %r exit %r" % (j["state"], j["result"], j["exit"]))


def c08():
    j = job(S("r4"), "FS")
    need(j["state"] == "broken", "state %r" % j["state"])


def c10():
    j = job(S("r6"), "SD")
    need(j["state"] == "broken" and isinstance(j["reason"], str) and j["reason"],
         "state %r reason %r" % (j["state"], j["reason"]))


def c11():
    s = S("r6")
    j = job(s, "SL")
    need(s["hb"] is not None and j["state"] in ("queued", "running"),
         "runner %r, state %r" % (s["hb"] is not None, j["state"]))


def c12():
    j = job(S("r7"), "SR")
    need(j["state"] == "done" and j["exit"] is None, "state %r exit %r" % (j["state"], j["exit"]))


def c13():
    s = S("r8")
    need("OLD" not in s["jobs"] and "OLD.log" not in s["files"],
         "job %r, log %r" % ("OLD" in s["jobs"], "OLD.log" in s["files"]))


def c14():
    s = S("r8")
    need(s["hb"] is not None and "YOUNG" in s["jobs"] and "YOUNG.log" in s["files"],
         "runner %r, job %r, log %r" % (s["hb"] is not None, "YOUNG" in s["jobs"], "YOUNG.log" in s["files"]))


def c19():
    j = job(S("r3"), "G1")
    need("process gone without a fresh record" in (j.get("reason") or ""), "reason %r" % j.get("reason"))


def answered_from_record(s, t):
    j = job(s, t)
    need(j["state"] == "done" and j.get("answered") is True and j.get("result") == "PASS" and j.get("exit") == 0,
         "state %r, answered %r, result %r, exit %r" % (j["state"], j.get("answered"), j.get("result"), j.get("exit")))
    hist = [h for h in s["history"] if h.get("hkey") == "k-" + t]
    need(not hist, "a history line was written: %r" % hist)


def c20():
    answered_from_record(S("r12"), "AA")


def c21():
    answered_from_record(S("r12"), "AR")


def c23():
    j = job(S("r12"), "AX")
    need(j["state"] == "broken" and not j.get("answered") and "without a fresh record" in (j.get("reason") or ""),
         "state %r, answered %r, reason %r" % (j["state"], j.get("answered"), j.get("reason")))


def c24():
    answered_from_record(S("r12"), "AW")


def c22():
    j = job(S("r11"), "AE")
    need(j["state"] == "running" and j.get("env", "absent") == SUBMITTED_ENV,
         "state %r, env %r" % (j["state"], j.get("env", "absent")))


def c25():
    j = job(S("r1-end"), "J1")
    need(j["state"] == "done" and j.get("env", "absent") == SUBMITTED_ENV,
         "state %r, env %r" % (j["state"], j.get("env", "absent")))


CHECKS = [
    (1, "a killed runner's running job is adopted: same pid, done with its record (PASS, exit 0)", c01),
    (2, "the queued jobs run after the restart", c02),
    (3, "each job's marker appears exactly once", c03),
    (4, "a running job with pid null is broken", c04),
    (5, "a broken job with pid null is not started on a later decision", c05),
    (6, "a running job whose pid is gone without a record is broken", c06),
    (7, "a running job whose pid is gone, with a record newer than its start, is done with the record's result", c07),
    (8, "a running job whose pid is gone, with a record older than its start, is broken", c08),
    (10, "a queued slot job whose pid is gone is broken", c10),
    (11, "a queued slot job whose pid is alive is not broken", c11),
    (12, "a running slot job whose pid is gone is done, exit null", c12),
    (13, "a finished job older than retention_hours is pruned with its log", c13),
    (14, "a finished job younger than retention_hours is kept with its log", c14),
    (19, "an adopted job whose pid is gone without a record is broken: without a fresh record", c19),
    (20, "an adopted job answered from an older record is done: answered, PASS, no history line", c20),
    (21, "an adopted job answered with a restamp is done: answered, PASS, no history line", c21),
    (22, "an adopted running job keeps its env, as submitted, after the first decision", c22),
    (23, "an answered line after other output is not zone-tool's: broken, not answered", c23),
    (24, "an answered line after --single's wait line is zone-tool's: done, answered", c24),
    (25, "an adopted job that then finishes keeps the env it was submitted with", c25),
]


def check():
    bad = []
    for num, label, fn in CHECKS:
        try:
            fn()
        except Exception as e:
            bad.append("%d %s" % (num, label))
            print("FAIL %d %s: %s: %s" % (num, label, type(e).__name__, e))
            continue
        print("ok   %d %s" % (num, label))
    summary = ("buildq-restart: %d of %d checks failed: %s" % (len(bad), len(CHECKS), "; ".join(bad))
               if bad else "buildq-restart: all %d checks ok" % len(CHECKS))
    with open(os.path.join(os.path.dirname(SNAP), "summary"), "w") as f:
        f.write(summary + "\n")
    return 1 if bad else 0


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "mkjobs":
        mkjobs(args[0], args[1])
    elif cmd == "snap":
        snap(args[0], args[1], args[2:])
    elif cmd == "reap":
        reap(args[0])
    elif cmd == "check":
        SNAP = args[0]
        sys.exit(check())
PY

mkdir -p "$tmp/stub"
# Exercise the load-bound race by delaying the runners' ps calls. The delay sleeps in the background so the
# stub's trap stops it when cleanup's pkill reaches the stub: no sleep outlives it.
if [ "${BUILDQ_RESTART_PS_DELAY+x}" ]; then
  printf '#!/bin/sh\n/bin/sleep %s &\nc=$!\ntrap "kill $c 2>/dev/null; exit 143" TERM INT\nwait "$c"\nexec /bin/ps "$@"\n' \
    "$BUILDQ_RESTART_PS_DELAY" > "$tmp/stub/ps"
  chmod +x "$tmp/stub/ps"
  printf "info: runners' ps delayed %s s (BUILDQ_RESTART_PS_DELAY)\n" "$BUILDQ_RESTART_PS_DELAY"
fi
# Time Machine is never touched: a stub tmutil (first on PATH) records its argv and exits 0.
cat > "$tmp/stub/tmutil" <<SH
#!/bin/sh
printf '%s\n' "\$*" >> "$tmp/tmutil.log"
exit 0
SH
chmod +x "$tmp/stub/tmutil"
# The job's tool: `test [flags] -- SECONDS MARK RECORD [EXIT]`, or `-- hold MARK RECORD RELEASE`.
# It marks its start, waits for the duration or release file, then writes its record.
cat > "$tmp/stub/zone-tool" <<'SH'
#!/bin/sh
while [ $# -gt 0 ] && [ "$1" != "--" ]; do shift; done
[ $# -gt 0 ] && shift
secs=$1 mark=$2 rec=$3 code=0
c=
trap '[ -z "$c" ] || { kill "$c" 2>/dev/null; wait "$c" 2>/dev/null; }; exit 143' TERM INT
echo "ticket=${CODETEAM_BUILDQ_TICKET:-unset} held=${CODETEAM_SLOT_HELD:-unset} foo=${FOO:-unset} cwd=$(pwd -P) pid=$$ nice=$(/bin/ps -o nice= -p $$ | tr -d ' ')" >> "$mark"
if [ "$secs" = hold ]; then
  while [ ! -e "$4" ]; do
    sleep 0.05 &
    c=$!
    wait "$c"
  done
else
  code=${4:-0}
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
# A build/test stand-in stays alive until signaled. Its trap stops and reaps the current sleep,
# including when cleanup finds the stub by its scratch path; no child sleep outlives the stub.
cat > "$tmp/stub/keep" <<'SH'
#!/bin/sh
c=
trap '[ -z "$c" ] || { kill "$c" 2>/dev/null; wait "$c" 2>/dev/null; }; exit 0' TERM INT
while :; do
  sleep 120 &
  c=$!
  wait "$c"
done
SH
chmod +x "$tmp/stub/keep"

# rn SC ARGS: one runner on scenario SC's queue, under env -i. RUNENV holds extra VAR=VALUE words (a later
# word wins); EXEC=exec makes the runner replace the calling subshell, so $! is its pid; RUNWRAP wraps it.
# once/loop use 120 s safety caps, return on runner exit, and retain its mode and exit code for snap.
rn() {
  local sc=$1
  shift
  ${RUNWRAP:-} ${EXEC:-} env -i PATH="$path" HOME="$tmp" CODETEAM_QUEUE_DIR="$sc/run/queue" \
    CODETEAM_BUILDQ_TICK=0.05 CODETEAM_BUILDQ_IDLE_EXIT=1 CODETEAM_BUILDQ_LOAD_FILE="$sc/load" \
    ${RUNENV:-} "$runner" "$@"
}
once() {
  RUNWRAP="/usr/bin/timeout 120" rn "$1" --once
  runner_rc=$? runner_mode=--once
  return "$runner_rc"
}
loop() {
  RUNWRAP="/usr/bin/timeout 120" rn "$1"
  runner_rc=$? runner_mode=loop
  return "$runner_rc"
}
pyl() { "$py" -I "$tmp/lib.py" "$@"; }
snap() {
  if [ "${runner_rc+x}" ]; then
    pyl snap "$@" runner_rc="$runner_rc" runner_mode="$runner_mode"
  else
    pyl snap "$@"
  fi
}
# newsc SC: a scenario folder with its worktree, marker, record and release folders, and a quiet load file.
newsc() {
  mkdir -p "$1/wt" "$1/marks" "$1/records" "$1/release" "$1/run/queue"
  printf '0.5\n0\n' > "$1/load"
}
# dead_pid prints a reaped orphan pid and its exit-wait outcome, not an age-based guess.
dead_pid() {
  local pid
  pid="$( ( /usr/bin/true >/dev/null 2>&1 & echo $! ) )"
  within 120 gone "$pid"
  printf '%s %s\n' "$pid" "$wait_outcome"
}
# live_pid TOOL NAME prints an orphan pid and its exec-wait outcome. The tool name must be visible to ps
# before a runner sees its job. Redirecting the child also closes the $( ) pipe.
live_pid() {
  local pid
  pid="$( ( "$1" >/dev/null 2>&1 & echo $! ) )"
  within 120 named "$pid" "$2"
  printf '%s %s\n' "$pid" "$wait_outcome"
}
named() { [[ "$(/bin/ps -o command= -p "$1" 2>/dev/null)" == *"$2"* ]]; }
# within SECS COMMAND... polls an event every 0.1 s and returns immediately on success. All callers
# allow at least 120 s as a stuck-event safety net and snapshot wait_outcome (ok/timeout).
within() {
  local end=$(( $(date +%s) + $1 ))
  shift
  wait_outcome=ok
  while ! "$@"; do
    if [ "$(date +%s)" -ge "$end" ]; then
      wait_outcome=timeout
      return 1
    fi
    sleep 0.1
  done
}
# gone PID: PID has exited (an orphan, so it is reaped and kill -0 fails).
gone() { ! kill -0 "$1" 2>/dev/null; }
# exited PID: PID is no longer running (a zombie child counts as exited).
exited() {
  case "$(/bin/ps -o stat= -p "$1" 2>/dev/null)" in
    ""|Z*) return 0 ;;
  esac
  return 1
}
# pid_or_exited FILE PID: the job file has a pid, or PID has exited.
pid_or_exited() { grep -Eq '"pid": *[0-9]' "$1" 2>/dev/null || exited "$2"; }
# A slot job's fields; the scenario adds ticket, state, pid, command and timing.
SLOT='"kind":"slot","class":"dev","tool":"cargo","record":null,"env":{},"key":"slot cargo"'
CARGO_BUILD='"command":["cargo","build"]'

sc_r1() {
  trap - EXIT
  local sc="$tmp/r1" a b pid_wait adopt_wait
  newsc "$sc"
  pyl mkjobs "$sc" '[{"ticket":"J1","submitted":1000,"sleep":"hold"},{"ticket":"J2","submitted":1001,"sleep":0.2},{"ticket":"J3","submitted":1002,"sleep":0.2}]'
  ( EXEC=exec RUNENV="CODETEAM_BUILD_BUDGET=1 CODETEAM_BUILDQ_IDLE_EXIT=0" rn "$sc" >/dev/null 2>&1 ) &
  a=$!
  within 120 pid_or_exited "$sc/run/queue/J1.json" "$a"
  pid_wait=$wait_outcome
  kill -9 "$a" 2>/dev/null
  wait "$a" 2>/dev/null
  snap r1-killed "$sc" pid_wait="$pid_wait"
  # A new heartbeat follows the restart's first complete decision, while J1 is still held.
  rm -f "$sc/run/queue-runner.json"
  RUNENV="CODETEAM_BUILD_BUDGET=1" loop "$sc" &
  b=$!
  within 120 test -e "$sc/run/queue-runner.json"
  adopt_wait=$wait_outcome
  touch "$sc/release/J1"
  wait "$b"
  runner_rc=$? runner_mode=loop
  snap r1-end "$sc" pid_wait="$pid_wait" adopt_wait="$adopt_wait"
}

sc_r2() {
  trap - EXIT
  local sc="$tmp/r2"
  newsc "$sc"
  pyl mkjobs "$sc" '[{"ticket":"NP","state":"running","started":900,"submitted":800,"pid":null}]'
  once "$sc"
  snap r2-1 "$sc"
  once "$sc"
  snap r2-2 "$sc"
}

sc_r3() {
  trap - EXIT
  local sc="$tmp/r3" dp
  newsc "$sc"
  read -r dp dead_wait <<< "$(dead_pid)"
  pyl mkjobs "$sc" "[{\"ticket\":\"G1\",\"state\":\"running\",\"started\":900,\"submitted\":800,\"pid\":$dp}]"
  once "$sc"
  snap r3 "$sc" dead_wait="$dead_wait"
}

sc_r4() {
  trap - EXIT
  local sc="$tmp/r4" dp now
  newsc "$sc"
  read -r dp dead_wait <<< "$(dead_pid)"
  now="$(date +%s)"
  printf '{"result": "FAIL", "exit": 1, "cpu_seconds": 2, "seconds": 3}\n' > "$sc/records/FR.json"
  printf '{"result": "PASS", "exit": 0, "cpu_seconds": 2, "seconds": 3}\n' > "$sc/records/FS.json"
  pyl mkjobs "$sc" "[{\"ticket\":\"FR\",\"state\":\"running\",\"started\":900,\"submitted\":800,\"pid\":$dp,\"record_mtime\":$((now - 100))},{\"ticket\":\"FS\",\"state\":\"running\",\"started\":900,\"submitted\":800,\"pid\":$dp,\"record_mtime\":$((now + 100))}]"
  once "$sc"
  snap r4 "$sc" dead_wait="$dead_wait"
}

sc_r6() {
  trap - EXIT
  local sc="$tmp/r6" dp lp
  newsc "$sc"
  read -r dp dead_wait <<< "$(dead_pid)"
  read -r lp keep_exec_wait <<< "$(live_pid "$tmp/stub/keep" keep)"
  pyl mkjobs "$sc" "[{\"ticket\":\"SD\",$SLOT,$CARGO_BUILD,\"pid\":$dp},{\"ticket\":\"SL\",$SLOT,$CARGO_BUILD,\"pid\":$lp}]"
  once "$sc"
  snap r6 "$sc" dead_wait="$dead_wait" keep_exec_wait="$keep_exec_wait"
  kill "$lp" 2>/dev/null
}

sc_r7() {
  trap - EXIT
  local sc="$tmp/r7" dp
  newsc "$sc"
  read -r dp dead_wait <<< "$(dead_pid)"
  pyl mkjobs "$sc" "[{\"ticket\":\"SR\",$SLOT,$CARGO_BUILD,\"state\":\"running\",\"started\":900,\"pid\":$dp}]"
  once "$sc"
  snap r7 "$sc" dead_wait="$dead_wait"
}

sc_r8() {
  trap - EXIT
  local sc="$tmp/r8" now
  newsc "$sc"
  now="$(date +%s)"
  printf 'retention_hours = 1\n' > "$sc/run/queue.toml"
  pyl mkjobs "$sc" "[{\"ticket\":\"OLD\",\"state\":\"done\",\"exit\":0,\"result\":\"PASS\",\"submitted\":$((now - 7400)),\"started\":$((now - 7300)),\"finished\":$((now - 7200))},{\"ticket\":\"YOUNG\",\"state\":\"done\",\"exit\":0,\"result\":\"PASS\",\"submitted\":$((now - 130)),\"started\":$((now - 120)),\"finished\":$((now - 60))}]"
  printf 'old output\n' > "$sc/run/queue/OLD.log"
  printf 'young output\n' > "$sc/run/queue/YOUNG.log"
  once "$sc"
  snap r8 "$sc"
}

# An adopted run job whose pid is alive: the first decision leaves its env as submitted.
sc_r11() {
  trap - EXIT
  local sc="$tmp/r11" lp now
  newsc "$sc"
  read -r lp keep_exec_wait <<< "$(live_pid "$tmp/stub/keep" keep)"
  now="$(date +%s)"
  pyl mkjobs "$sc" "[{\"ticket\":\"AE\",\"state\":\"running\",\"started\":$now,\"submitted\":800,\"pid\":$lp}]"
  once "$sc"
  snap r11 "$sc" keep_exec_wait="$keep_exec_wait"
  kill "$lp" 2>/dev/null
}

# Adopted run jobs whose pid is gone: AA's log has the already-recorded line and its record predates record_mtime;
# AR's log has the restamp line and its record is newer than record_mtime.
sc_r12() {
  trap - EXIT
  local sc="$tmp/r12" dp now
  newsc "$sc"
  read -r dp dead_wait <<< "$(dead_pid)"
  now="$(date +%s)"
  printf '{"result": "PASS", "exit": 0, "cpu_seconds": 1, "seconds": 1}\n' > "$sc/records/AA.json"
  printf '{"result": "PASS", "exit": 0, "cpu_seconds": 1, "seconds": 1}\n' > "$sc/records/AR.json"
  printf 'zone-test: PASS at 12:00 already recorded for this exact code; not run again\n' > "$sc/run/queue/AA.log"
  printf 'zone-test: PASS at 12:00 already recorded; nothing these tests touch has changed since; not run again\n' \
    > "$sc/run/queue/AR.log"
  # AX: the answered line is not zone-tool's own: a crashed test printed it later in its output (or a nested
  # `zone-tool job submit --cached` did), and an older PASS record exists. AW: --single waited for a run that was
  # already going, which is zone-tool's own first line, and the answered line comes second.
  printf '{"result": "PASS", "exit": 0, "cpu_seconds": 1, "seconds": 1}\n' > "$sc/records/AX.json"
  printf '{"result": "PASS", "exit": 0, "cpu_seconds": 1, "seconds": 1}\n' > "$sc/records/AW.json"
  printf 'some test output\nzone-test: PASS at 12:00 already recorded for this exact code; not run again\nTraceback (most recent call last):\n' \
    > "$sc/run/queue/AX.log"
  printf 'zone-test: a run is already going in this worktree; waiting for its result\nzone-test: PASS at 12:00 already recorded for this exact code; not run again\n' \
    > "$sc/run/queue/AW.log"
  pyl mkjobs "$sc" "[{\"ticket\":\"AA\",\"state\":\"running\",\"started\":900,\"submitted\":800,\"pid\":$dp,\"record_mtime\":$((now + 100))},{\"ticket\":\"AR\",\"state\":\"running\",\"started\":900,\"submitted\":800,\"pid\":$dp,\"record_mtime\":$((now - 100))},{\"ticket\":\"AX\",\"state\":\"running\",\"started\":900,\"submitted\":800,\"pid\":$dp,\"record_mtime\":$((now + 100))},{\"ticket\":\"AW\",\"state\":\"running\",\"started\":900,\"submitted\":800,\"pid\":$dp,\"record_mtime\":$((now + 100))}]"
  once "$sc"
  snap r12 "$sc" dead_wait="$dead_wait"
}

sc_r1 &
sc_r2 &
sc_r3 &
sc_r4 &
sc_r6 &
sc_r7 &
sc_r8 &
sc_r11 &
sc_r12 &
wait

stage=checking
pyl check "$tmp/snap"
exit $?
