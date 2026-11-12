#!/bin/bash
# zone/tests/zone-job.sh: zone-tool job submit, wait and status (the build queue), run through
# zone-tool itself against a fake runner this test writes and starts through fake-launchctl. No real runner and no live queue: every
# check has its own scratch repo, queue and runner, and the checks run side by side. zone-tool runs
# under env -i with a stub PATH, and a stub tmutil first on that PATH (zone/docs/TESTING.md): no check reaches the real Time
# Machine. zone-job-mk.sh checks the make targets. ZONE_JOB_RUNNER_DELAY delays fake runners to expose
# startup races; the EXIT trap prints a case summary on stderr.
# slow: about 85 zone-tool runs pay Python and git start-up; runner readiness and check 31's stale-beat
# signal are event waits, and check 30 synchronizes state reads through a FIFO. A measured plain
# run took 17 s wall, 12.1 s CPU, at load 64.1 on 18 CPUs, over all 35 checks.
#  01 submit prints one ticket line; Q/<ticket>.json has the contract's fields (state queued), mode
#     0600; a runner it finds with a free lock is started.
#  02 submit --class bogus: exit 2, no job file.
#  03 job wait on a queued job: exit 4, "WAITING: queued, number N in class dev", and the last line
#     "WAITING: zone-tool job wait <ticket>".
#  04 submit --wait 1 on a queued job: exit 4, and its last line names a queued ticket.
#  05 submit --single: an identical queued job answers with its ticket; another command gets its own.
#  06 job status: a budget/swap header with no load in it, and one line for the queued job; job status <ticket> too.
#  07 job status with no runner: "runner: not running", exit 0.
#  08 job wait on a passing run: exit 0, the job's log, "zone-test: PASS (exit 0); record <path>".
#  09 a failing run: job wait still exits 0 and the summary says "zone-test: FAIL (exit 1)".
#  10 a broken job: job wait exits 3 and prints "BROKEN: <reason>".
#  11 job wait on an unknown ticket: exit 2.
#  12 submit --wait on a passing test: exit 0, the summary line.
#  13 submit --wait, the test exits 1: exit 1.
#  14 submit --wait, the test exits 3: exit 1 (never 3).
#  15 submit --wait, the test exits 4: exit 1 (never 4).
#  16 submit --wait on a broken job: exit 3.
#  17 submit --cached on unchanged code: prints what zone-tool test --cached prints, writes no job file,
#     and the test ran once (the first run).
#  18 submit --cached --wait: a PASS record exits 0, a FAIL record exits 1.
#  19 CODETEAM_BUILDQ_TICKET set (a nested submit): the test runs here, exit = the test's exit, no job
#     file, no runner started.
#  20 no runner (CODETEAM_BUILDQ=/nonexistent): stderr "build queue unavailable", the test runs here
#     with its own exit, and any job file ends done with fallback true. env: the job file keeps the
#     submitter's env once claimed (the test's own command reads it while it runs) and once done.
#  21 a stale heartbeat (a runner holds the lock and does not beat): the same as 20, the env check included.
#  22 fallback compare-and-swap: a runner that already marked the job running runs it; the submitter
#     does not run it again (exit 0, one run, fallback false).
#  23 zone-test --cached on unchanged code: answered from the record, not run again. This is zone-tool
#     test's behaviour; the check guards that the shared record check did not change it.
#  24 zone-test --scope: a change outside the scope restamps the record, and covered reads it as current.
#     zone-tool test's behaviour, guarded as 23 is.
#  25 the runner submit starts is nobody's descendant: its parent is init (pid 1), so a tree kill of the
#     submitter does not reach it.
#  26 job wait on a queued job whose file has hold set: the WAITING line ends ", held: warm".
#  27 the fallback marks its job with started and record_mtime (the record's mtime before the in-process run).
#  28 a queue-runner.json with no beat (a runner holding the lock): the same fallback as 20, the env check included.
#  29 a foreign file in the queue ({} as Q/x.json): submit --wait still runs the job; status skips the file.
#  30 submit --wait reads a fresh state from a lock-holding runner's FIFO, then stale states: a watchdog checks
#     for a blocked read; the test runs here with stderr naming the unresponsive runner, and ends done, fallback true, exit 8.
#     Integration group only (CODETEAM_TEST_GROUP=integration), skipped otherwise.
#  31 submit prints a ticket while the runner beats fresh; a signal makes it publish a stale beat and stop.
#     job wait alone prints "WAITING: the runner is not responding (last beat N s ago)", then the wait line, exit 4.
#  32 --wait auto: the seconds are BASH_DEFAULT_TIMEOUT_MS/1000 less 60 (at least 30), else 100; submit
#     accepts it. The arithmetic is read from zone-tool's own wait_seconds, since a real wait is over 30 s.
#  33 Time Machine: a submit that creates the queue Q makes no tmutil call, and Q is created 0700.
#  34 Time Machine: a submit into an existing Q makes no tmutil call.
#  35 a done job with answered true: job wait exits 0 and its summary line is "zone-test: PASS (exit 0);
#     answered from record <record>".
set -u
unset MAKEFLAGS MFLAGS MAKELEVEL MAKEOVERRIDES MAKEFILES CODETEAM_ZONE CODETEAM_OWNS DIR \
      GIT_DIR GIT_INDEX_FILE GIT_WORK_TREE CODETEAM_BUILDQ_TICKET CODETEAM_SLOT_HELD
# Stage 2 (v5.2) sets GROUP and CODETEAM_TEST_GROUP: children must not inherit them or their record keys change.
# export -n keeps the outer values available to this script without exporting them.
export -n GROUP CODETEAM_TEST_GROUP
here="$(cd "$(dirname "$0")/../.." && pwd)"
ZT="$here/bin/zone-tool"
PY=python3
# /tmp, not TMPDIR: a session's TMPDIR can sit under a team-<x> folder, and a job records the first one of those.
tmp="$(mktemp -d /tmp/zone-job.XXXXXX)"
stage="setup"
summary=""
cleanup() {
  local rc=$?
  trap - EXIT
  kill $(jobs -p) $(cat "$tmp"/c*/pids 2>/dev/null) 2>/dev/null
  if [ -z "$summary" ]; then
    summary="zone-job: FAIL: no check summary ($stage, exit $rc)"
  fi
  rm -rf "$tmp"
  printf '%s\n' "$summary" >&2
  exit "$rc"
}
trap cleanup EXIT
# Delay startup to reproduce races between a submitter and its fake runner.
if [ -n "${ZONE_JOB_RUNNER_DELAY:-}" ]; then
  printf 'info: fake runners start %s s late (ZONE_JOB_RUNNER_DELAY)\n' "$ZONE_JOB_RUNNER_DELAY"
fi
export GIT_CEILING_DIRECTORIES="$tmp"
mkdir -p "$tmp/home"
res="$tmp/results"; mkdir -p "$res"
FAKE="$tmp/fake-runner.py"
NUMS="01 02 03 04 05 06 07 08 09 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35"
# Time Machine guard (zone/docs/TESTING.md): a stub tmutil first on the PATH of every zone-tool call. It appends its argv to $TMUTIL_LOG and
# exits 0, so no check reaches the real Time Machine. A check that finds the log non-empty has seen a tmutil call.
P="$tmp/stub:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
mkdir -p "$tmp/stub"
cat > "$tmp/stub/tmutil" <<'SH'
#!/bin/sh
echo "$*" >> "$TMUTIL_LOG"
exit 0
SH
chmod +x "$tmp/stub/tmutil"

cat > "$FAKE" <<'PY'
# Fake build-queue runner for zone-job.sh: it stands in for codeteam-buildq. argv[1] is the mode.
# run: starts queued run jobs, one at a time, and finishes each from its record.
# claim: as run, but its heartbeat is stale from the start (a runner that claims late).
# never: a fresh heartbeat and no starts. break: marks each queued job broken.
# stale: a stale heartbeat and no starts.
# fifo-hang: serve one fresh state read, then stale reads through a FIFO; no starts.
# hold-hang: beat fresh until the case creates hang, publish a stale beat and hung, then stop beating; no starts.
# Both hang modes age the beat by 1000 s to exceed STALE without waiting for real time to pass.
# nobeat: a state file with no beat in it, and no starts.
import fcntl, json, os, subprocess, sys, time
from pathlib import Path

mode = sys.argv[1]
q = Path(os.environ["CODETEAM_QUEUE_DIR"])
root = q.parent
tick = float(os.environ.get("CODETEAM_BUILDQ_TICK", "1"))
idle_exit = float(os.environ.get("CODETEAM_BUILDQ_IDLE_EXIT", "0"))
q.mkdir(parents=True, exist_ok=True)
lock = open(q / ".runner.lock", "a")
import time as _t
_deadline = _t.monotonic() + 0.5
while True:   # a client probe (brief LOCK_NB) may hold it for an instant: retry, as bin/codeteam-buildq does
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        break
    except BlockingIOError:
        if _t.monotonic() >= _deadline:
            sys.exit(0)
        _t.sleep(0.02)


def write(path, obj):
    tmp = path.with_name("." + path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def update(path, **changes):
    with open(q / ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        job = json.loads(path.read_text())
        job.update(changes)
        write(path, job)
    return job


def queued():
    return [p for p in sorted(q.glob("*.json")) if json.loads(p.read_text()).get("state") == "queued"]


def start(p):
    job = update(p, state="running", started=time.time(), pid=None)
    log = open(q / (job["ticket"] + ".log"), "w")
    env = dict(job["env"], CODETEAM_SLOT_HELD="1", CODETEAM_BUILDQ_TICKET=job["ticket"])
    child = subprocess.Popen([job["tool"], "test", *job["test_flags"], "--", *job["command"]],
                             cwd=job["worktree"], env=env, stdin=subprocess.DEVNULL,
                             stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    update(p, pid=child.pid)
    return p, child


def finish(p, child):
    record = Path(json.loads(p.read_text())["record"])
    rec = json.loads(record.read_text()) if record.exists() else {}
    update(p, state="done", exit=rec.get("exit", child.returncode), result=rec.get("result"),
           finished=time.time(), pid=None)


running = None
last_busy = time.time()
beaten = False
hung = False
if mode == "fifo-hang":
    os.mkfifo(root / "queue-runner.json", 0o600)
while True:
    state = {
        "pid": os.getpid(), "beat": 0 if mode in ("claim", "stale") else time.time(),
        "budget": 6, "used": 0, "swap": 0.0, "swap_max": 0.9, "swap_hold": False}
    if mode == "nobeat":
        del state["beat"]
    if mode == "fifo-hang":
        try:
            with (root / "queue-runner.json").open("w") as pipe:
                # Compute freshness after the reader arrives, not before the blocking open.
                state["beat"] = time.time() - (1000 if beaten else 0)
                if beaten:
                    (root.parent / "hung").touch()
                json.dump(state, pipe)
        except BrokenPipeError:
            pass
        beaten = True
    elif not hung:
        hung = mode == "hold-hang" and (root.parent / "hang").exists()
        if hung:
            state["beat"] = time.time() - 1000
        write(root / "queue-runner.json", state)
        if hung:
            (root.parent / "hung").touch()
    pending = queued()
    if mode == "break":
        for p in pending:
            update(p, state="broken", reason="fake runner could not start it", finished=time.time())
    elif mode in ("run", "claim"):
        if running is None and pending:
            running = start(pending[0])
        elif running is not None and running[1].poll() is not None:
            finish(*running)
            running = None
    if running is not None or pending or mode in ("never", "stale", "fifo-hang", "hold-hang", "nobeat"):
        last_busy = time.time()
    elif idle_exit and time.time() - last_busy >= idle_exit:
        break
    time.sleep(tick)
PY

JCHECK="$tmp/jcheck.py"
cat > "$JCHECK" <<'PY'
# jcheck.py CASE JOB-FILE [ARG...] < checks: each line "label :: expression", printed ok or FAIL. The expression
# sees d (the job file's JSON), f (its path), a (the ARGs) and os, hashlib. An unreadable file fails every check.
import hashlib, json, os, sys
case, f, a = sys.argv[1], sys.argv[2], sys.argv[3:]
try:
    d = json.load(open(f))
except (OSError, ValueError):
    d = {}
for line in sys.stdin:
    label, _, expr = line.rstrip("\n").partition(" :: ")
    try:
        good = bool(eval(expr))
    except Exception:
        good = False
    print(("ok   " if good else "FAIL ") + case + " " + label)
PY

# zone-tool as a submitter runs it: env -i, a stub PATH, this check's queue and runner. ZX adds variables.
zt() {
  env -i PATH="$P" HOME="$tmp/home" TMPDIR="$tmp" GIT_CEILING_DIRECTORIES="$tmp" TMUTIL_LOG="$c/tmutil.log" \
    CODETEAM_QUEUE_DIR="$Q" CODETEAM_BUILDQ="$BQ" CODETEAM_BUILDQ_LAUNCH="$here/zone/tests/fake-launchctl" CODETEAM_BUILDQ_TICK=0.05 CODETEAM_BUILDQ_IDLE_EXIT=1 \
    CODETEAM_BUILDQ_START_WAIT=10 CODETEAM_BUILDQ_STALE=2 CODETEAM_SESSION=S1 $ZX \
    "$PY" "$ZT" "$@"
}
# A runner of this check: a wrapper that records its pid and that it started, then runs FAKE in mode $1.
mkbq() {
  printf '#!/bin/sh\necho $$ >> %s\n: > %s\n' "$c/pids" "$c/started" > "$BQ"
  # The delay sleeps in the background so the wrapper's trap stops it when the check kills the wrapper's pid.
  if [ -n "${ZONE_JOB_RUNNER_DELAY:-}" ]; then
    printf '/bin/sleep %q &\nd=$!\ntrap "kill $d 2>/dev/null; exit 143" TERM INT\nwait "$d"\ntrap - TERM INT\n' \
      "$ZONE_JOB_RUNNER_DELAY" >> "$BQ"
  fi
  printf 'exec %s -I %s %s\n' "$PY" "$FAKE" "$1" >> "$BQ"
  chmod +x "$BQ"
}
# Wait for a runner's file event, allowing loaded machines two minutes without delaying a ready event.
wait_file() {
  "$PY" -I -c 'import sys,time; from pathlib import Path
p = Path(sys.argv[1])
deadline = time.monotonic() + 120
while not p.exists():
    if time.monotonic() >= deadline:
        sys.exit(1)
    time.sleep(0.05)
' "$1"
}
start_runner() {  # start in the background, then wait for its first state file (even a stale or beatless one)
  CODETEAM_QUEUE_DIR="$Q" CODETEAM_BUILDQ_TICK=0.05 CODETEAM_BUILDQ_IDLE_EXIT=1 "$BQ" > /dev/null 2>&1 &
  wait_file "$Q/../queue-runner.json"
}
run()   { local n=$1; shift; "$@" > "$c/$n.out" 2>&1; rc=$?; }
runse() { local n=$1; shift; "$@" > "$c/$n.out" 2> "$c/$n.err"; rc=$?; }
ck()    { local l=$1; shift; if "$@" 2>/dev/null; then echo "ok   $cn $l"; else echo "FAIL $cn $l"; fi >> "$res/$cn"; }
eq()    { if [ "$2" = "$3" ]; then echo "ok   $cn $1"; else echo "FAIL $cn $1: got [$2], want [$3]"; fi >> "$res/$cn"; }
jcheck() { "$PY" -I "$JCHECK" "$cn" "$@" >> "$res/$cn"; }  # the checks on stdin, one Python run for all of them
jx()    { "$PY" -I -c 'import hashlib,json,os,sys; d=json.load(open(sys.argv[1])); a=sys.argv[3:]; sys.exit(0 if eval(sys.argv[2]) else 1)' "$@"; }
count() { [ -e "$1" ] && wc -l < "$1" | tr -d ' ' || echo 0; }
lastline() { tail -n 1 "$1"; }
jset()  { "$PY" -I -c 'import json,sys; d=json.load(open(sys.argv[1])); d[sys.argv[2]]=sys.argv[3]; json.dump(d,open(sys.argv[1],"w"))' "$@"; }
jget()  { "$PY" -I -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$@"; }
# a job done with a PASS and answered: true, as a run that zone-tool test answered from its record leaves it
jdone() { "$PY" -I -c 'import json,sys,time; p=sys.argv[1]; d=json.load(open(p)); d.update(state="done", exit=0, result="PASS", finished=time.time(), answered=True); json.dump(d,open(p,"w"))' "$1"; }
mtime() { "$PY" -I -c 'import os,sys; print(os.path.getmtime(sys.argv[1]))' "$1"; }
pmode() { "$PY" -I -c 'import os,sys; print(oct(os.stat(sys.argv[1]).st_mode & 0o777))' "$1"; }
# env: a fallback job keeps the submitter's env in every state: once claimed (the test's command, run in-process
# after the claim, copied the job file to $c/claimed.json) and once done. $1 is the job file; $P is the submitter's PATH.
k1()    {
  jcheck "$c/claimed.json" "$P" <<'CHECKS'
claimed (running, fallback): env kept :: d["state"] == "running" and d["fallback"] is True and d["env"].get("CODETEAM_SESSION") == "S1" and d["env"].get("PATH") == a[0]
CHECKS
  jcheck "$1" "$P" <<'CHECKS'
done: env kept :: d["state"] == "done" and d["env"].get("CODETEAM_SESSION") == "S1" and d["env"].get("PATH") == a[0]
CHECKS
}
# wait_seconds as zone-tool reads it: the module loaded (not run) under env -i plus ZX, `--wait` text $1.
wsec()  { env -i PATH="$P" $ZX "$PY" -I -c 'import importlib.machinery as m, importlib.util as u, sys; l = m.SourceFileLoader("zt", sys.argv[1]); mod = u.module_from_spec(u.spec_from_loader("zt", l)); l.exec_module(mod); print(mod.wait_seconds(sys.argv[2]))' "$ZT" "$1"; }
ticket() {  # the ticket a submit printed, or "none" when its output is not one (so the checks after it fail)
  if grep -Eq '^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$' "$1"; then cat "$1"; else echo none; fi
}

launch() {  # $1 the check's number, $2 its function: a repo (a copy of the template), a queue and a runner of its own
  (
    cn=$1; c="$tmp/c$1"; R="$c/team-x/repo"; Q="$c/run/queue"; BQ="$c/buildq"; ZX=""
    mkdir -p "$c/team-x" && cp -R "$tmp/template" "$R" && cd "$R" || exit 1
    "$2"
    kill $(cat "$c/pids" 2>/dev/null) 2>/dev/null
  ) &
}

case_01() {
  mkbq never
  runse s zt job submit --class dev --key "one pkg" --scope pkg --timeout 5400 -- true
  eq "submit exit" "$rc" 0
  ck "stdout is one ticket line" grep -Eq '^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$' "$c/s.out"
  eq "stdout is that line alone" "$(count "$c/s.out")" 1
  tk=$(ticket "$c/s.out"); j="$Q/$tk.json"
  ck "submit started the runner (its mark is there on return)" [ -e "$c/started" ]
  ck "job file written" [ -f "$j" ]
  jcheck "$j" "$R" "$ZT" <<'CHECKS'
job is a run :: d["kind"] == "run"
class is dev :: d["class"] == "dev"
key is the submitted key :: d["key"] == "one pkg"
command is the argv :: d["command"] == ["true"]
test_flags are the submitted options :: d["test_flags"] == ["--key", "one pkg", "--scope", "pkg", "--timeout", "5400"]
state is queued :: d["state"] == "queued"
session is the submitter's :: d["session"] == "S1"
team is the first team- part :: d["team"] == "team-x"
worktree is the repo :: os.path.realpath(d["worktree"]) == os.path.realpath(a[0])
tool is this zone-tool :: os.path.realpath(d["tool"]) == os.path.realpath(a[1])
env is the submitter's :: d["env"].get("CODETEAM_SESSION") == "S1" and "PATH" in d["env"]
record is zone-tool's record for the key :: os.path.realpath(d["record"]) == os.path.realpath(a[0]) + "/.test-record-" + hashlib.sha256(b"one pkg").hexdigest()[:12] + ".json"
warm_lock is the git dir's lock :: os.path.realpath(d["warm_lock"]) == os.path.realpath(a[0] + "/.git/codeteam-warm.lock")
job file mode is 0600 :: os.stat(f).st_mode & 0o777 == 0o600
CHECKS
}

case_02() {
  mkbq never
  run s zt job submit --class bogus -- true
  eq "unknown class: exit 2" "$rc" 2
  ck "no job file" [ -z "$(ls "$Q" 2>/dev/null | grep '\.json$')" ]
}

case_03() {
  mkbq never
  run s zt job submit -- true
  tk=$(ticket "$c/s.out")
  run w zt job wait "$tk" --max 1
  eq "job wait on a queued job: exit 4" "$rc" 4
  ck "a WAITING line: queued, number N in class dev" grep -Eq '^WAITING: queued, number [0-9]+ in class dev' "$c/w.out"
  eq "last line names the wait" "$(lastline "$c/w.out")" "WAITING: zone-tool job wait $tk"
}

case_04() {
  mkbq never
  run w zt job submit --wait 1 -- true
  eq "submit --wait on a queued job: exit 4" "$rc" 4
  last=$(lastline "$c/w.out")
  ck "last line: WAITING: zone-tool job wait <ticket>" grep -Eq '^WAITING: zone-tool job wait [0-9]{8}-[0-9]{6}-[0-9a-f]{6}$' <(echo "$last")
  ck "that ticket is queued" jx "$Q/${last##* }.json" 'd["state"] == "queued"'
}

case_05() {
  mkbq never
  run a zt job submit --single -- true
  s1=$(ticket "$c/a.out")
  run b zt job submit --single -- true
  s2=$(ticket "$c/b.out")
  run d zt job submit --single -- sh -c 'echo other'
  s3=$(ticket "$c/d.out")
  ck "the first submit answers with a ticket" test "$s1" != none
  ck "an identical queued job answers with that ticket" test "$s2" = "$s1" -a "$s1" != none
  ck "another command gets its own ticket" test "$s3" != none -a "$s3" != "$s1"
  eq "two job files, not three" "$(ls "$Q" 2>/dev/null | grep -c '\.json$')" 2
}

case_06() {
  mkbq never
  run s zt job submit -- true
  tk=$(ticket "$c/s.out")
  run st zt job status
  eq "job status: exit 0" "$rc" 0
  ck "header: budget and swap" grep -Eq '^budget [0-9]+/[0-9]+ swap [0-9.]+/[0-9.]+' <(head -n 1 "$c/st.out")
  ck "header: no load" bash -c '! head -n 1 "$1" | grep -q load' _ "$c/st.out"
  eq "one line for the queued job, plus the header" "$(count "$c/st.out")" 2
  ck "the job's line: class, state, queued N s" grep -Eq "^$tk dev queued .*queued [0-9]+ s" "$c/st.out"
  run one zt job status "$tk"
  eq "job status <ticket>: exit 0" "$rc" 0
  ck "job status <ticket> names that job" grep -q "^$tk " "$c/one.out"
}

case_07() {
  BQ=/nonexistent
  run st zt job status
  eq "job status with no runner: exit 0" "$rc" 0
  eq "first line" "$(head -n 1 "$c/st.out")" "runner: not running"
}

case_08() {
  mkbq run
  run s zt job submit -- sh -c 'echo ticket-log-line; exit 0'
  tk=$(ticket "$c/s.out")
  run w zt job wait "$tk" --max 30
  eq "job wait on a passing run: exit 0" "$rc" 0
  ck "prints the job's log" grep -q '^ticket-log-line$' "$c/w.out"
  ck "last line: zone-test: PASS (exit 0); record <path>" grep -Eq '^zone-test: PASS \(exit 0\); record /.+\.test-record\.json$' <(lastline "$c/w.out")
  ck "the record it names is on disk" [ -f "$R/.test-record.json" ]
}

case_09() {
  mkbq run
  run s zt job submit -- sh -c 'echo nope-log; exit 1'
  tk=$(ticket "$c/s.out")
  run w zt job wait "$tk" --max 30
  eq "a failing run: job wait exit 0" "$rc" 0
  ck "last line: zone-test: FAIL (exit 1)" grep -Fq "zone-test: FAIL (exit 1); record /" <(lastline "$c/w.out")
  ck "prints the log" grep -q '^nope-log$' "$c/w.out"
}

case_10() {
  mkbq break
  run s zt job submit -- true
  tk=$(ticket "$c/s.out")
  run w zt job wait "$tk" --max 10
  eq "a broken job: job wait exit 3" "$rc" 3
  ck "BROKEN: <reason>" grep -q '^BROKEN: fake runner could not start it$' "$c/w.out"
}

case_11() {
  BQ=/nonexistent
  run w zt job wait 20990101-000000-abcdef --max 1
  eq "job wait on no such ticket: exit 2" "$rc" 2
}

case_12() {
  mkbq run
  run w zt job submit --wait 30 -- sh -c 'echo pass-log; exit 0'
  eq "submit --wait on a passing test: exit 0" "$rc" 0
  ck "last line: zone-test: PASS (exit 0)" grep -Fq "zone-test: PASS (exit 0); record /" <(lastline "$c/w.out")
}

submit_fail() {  # $1 the test's exit code: submit --wait exits 1, and the summary keeps the test's exit
  mkbq run
  run w zt job submit --wait 30 -- sh -c "exit $1"
  eq "submit --wait, the test exits $1: exit 1, and its summary keeps exit $1" "$rc:$(grep -cF "zone-test: FAIL (exit $1); record /" "$c/w.out")" "1:1"
}
case_13() { submit_fail 1; }
case_14() { submit_fail 3; }
case_15() { submit_fail 4; }

case_16() {
  mkbq break
  run w zt job submit --wait 10 -- true
  eq "submit --wait on a broken job: exit 3" "$rc" 3
  ck "BROKEN: <reason>" grep -q '^BROKEN: fake runner could not start it$' "$c/w.out"
}

case_17() {
  BQ=/nonexistent
  run p zt test -- sh -c "echo ran >> $c/ran"
  run k zt test --cached -- sh -c "echo ran >> $c/ran"
  run s zt job submit --cached -- sh -c "echo ran >> $c/ran"
  eq "submit --cached on unchanged code: exit 0" "$rc" 0
  ck "prints what zone-tool test --cached prints" cmp -s "$c/s.out" "$c/k.out"
  eq "the test ran once, on the first run" "$(count "$c/ran")" 1
  ck "no job file" [ -z "$(ls "$Q" 2>/dev/null | grep '\.json$')" ]
}

case_18() {
  BQ=/nonexistent
  run p zt test -- true
  run s zt job submit --cached --wait 5 -- true
  eq "a PASS record under --wait: exit 0" "$rc" 0
  run f zt test --key f -- sh -c 'exit 1'
  run g zt job submit --cached --wait 5 --key f -- sh -c 'exit 1'
  eq "a FAIL record under --wait: exit 1, answered from that record" "$rc:$(grep -cE 'zone-test: FAIL at .* already recorded' "$c/g.out")" "1:1"
}

case_19() {
  mkbq never
  ZX="CODETEAM_BUILDQ_TICKET=20990101-000000-abcdef"
  run s zt job submit -- sh -c 'echo nested-here; exit 6'
  eq "nested submit: exit is the test's" "$rc" 6
  ck "the test ran here" grep -q '^nested-here$' "$c/s.out"
  ck "no job file" [ -z "$(ls "$Q" 2>/dev/null | grep '\.json$')" ]
  ck "no runner started" [ ! -e "$c/started" ]
  ck "its record is on disk" [ -f "$R/.test-record.json" ]
}

case_20() {
  BQ=/nonexistent
  runse s zt job submit -- sh -c "cat $Q/*.json > $c/claimed.json; echo fb-here; exit 5"
  eq "no runner: exit is the test's" "$rc" 5
  ck "stderr: build queue unavailable" grep -q 'build queue unavailable' "$c/s.err"
  ck "the test ran here" grep -q '^fb-here$' "$c/s.out"
  set -- "$Q"/*.json
  if [ -e "$1" ]; then
    ck "its job file ends done, fallback true, exit 5" jx "$1" 'd["state"] == "done" and d["fallback"] is True and d["exit"] == 5'
    k1 "$1"
  else
    echo "ok   $cn no job file was written" >> "$res/$cn"
  fi
}

case_21() {
  mkbq stale
  ZX="CODETEAM_BUILDQ_START_WAIT=1 CODETEAM_BUILDQ_STALE=1"
  ck "the stale runner is up (it holds the lock)" start_runner
  runse s zt job submit -- sh -c "cat $Q/*.json > $c/claimed.json; echo stale-here; exit 7"
  eq "stale runner: exit is the test's" "$rc" 7
  ck "stderr: build queue unavailable" grep -q 'build queue unavailable' "$c/s.err"
  ck "the test ran here" grep -q '^stale-here$' "$c/s.out"
  set -- "$Q"/*.json
  if [ -e "$1" ]; then
    ck "its job file ends done, fallback true, exit 7" jx "$1" 'd["state"] == "done" and d["fallback"] is True and d["exit"] == 7'
    k1 "$1"
  else
    echo "ok   $cn no job file was written" >> "$res/$cn"
  fi
}

case_22() {
  mkbq claim
  ZX="CODETEAM_BUILDQ_STALE=1"   # START_WAIT stays the base 10 s: a loaded machine can take seconds to let the runner start the job
  ck "the claiming runner is up" start_runner
  run w zt job submit --wait 30 -- sh -c "echo x >> $c/mark"
  eq "submit --wait: DONE, exit 0" "$rc" 0
  eq "the test ran once" "$(count "$c/mark")" 1
  set -- "$Q"/*.json
  ck "the runner marked the job (fallback false)" jx "$1" 'd["state"] == "done" and d["fallback"] is False'
}

case_23() {
  BQ=/nonexistent
  run p zt test -- sh -c "echo ran >> $c/ran"
  run k zt test --cached -- sh -c "echo ran >> $c/ran"
  eq "zone-test --cached on unchanged code: exit 0" "$rc" 0
  ck "says it is recorded and not run again" grep -q 'already recorded for this exact code; not run again' "$c/k.out"
  eq "the test ran once" "$(count "$c/ran")" 1
}

case_24() {
  BQ=/nonexistent
  touch pkg/Package.swift
  echo notes > NOTES.md
  run p zt test --cached --key "k pkg" --scope pkg -- sh -c "echo ran >> $c/ran"
  echo notes2 > NOTES.md
  run k zt test --cached --key "k pkg" --scope pkg -- sh -c "echo ran >> $c/ran"
  eq "zone-test --scope, a change outside the scope: exit 0" "$rc" 0
  ck "says nothing these tests touch has changed" grep -q 'nothing these tests touch has changed' "$c/k.out"
  eq "the test ran once" "$(count "$c/ran")" 1
  run cv zt covered
  eq "covered reads the restamped record: exit 0" "$rc" 0
}

case_25() {
  mkbq never
  run s zt job submit -- true
  eq "the runner's parent is init" "$(ps -o ppid= -p "$(head -n 1 "$c/pids")" | tr -d ' ')" 1
}

case_26() {
  mkbq never
  run s zt job submit -- true
  tk=$(ticket "$c/s.out")
  jset "$Q/$tk.json" hold warm
  run w zt job wait "$tk" --max 1
  eq "job wait: exit 4" "$rc" 4
  ck "the WAITING line ends held: warm" grep -Eq '^WAITING: queued, number [0-9]+ in class dev, estimated start [^,]+, held: warm$' "$c/w.out"
}

case_27() {
  mkbq stale
  ZX="CODETEAM_BUILDQ_START_WAIT=1 CODETEAM_BUILDQ_STALE=1"
  ck "the stale runner is up" start_runner
  run p zt test -- true
  m=$(mtime "$R/.test-record.json")
  run s zt job submit -- true
  set -- "$Q"/*.json
  jcheck "$1" "$m" <<'CHECKS'
the fallback job is done :: d["state"] == "done" and d["fallback"] is True
started is set :: isinstance(d["started"], float)
record_mtime is the record's mtime before the run :: abs(d["record_mtime"] - float(a[0])) < 0.001
CHECKS
}

case_28() {
  mkbq nobeat
  ZX="CODETEAM_BUILDQ_START_WAIT=1 CODETEAM_BUILDQ_STALE=1"
  ck "the runner is up (state file without a beat)" start_runner
  runse s zt job submit -- sh -c "cat $Q/*.json > $c/claimed.json; echo nb-here; exit 9"
  eq "exit is the test's" "$rc" 9
  ck "stderr: build queue unavailable" grep -q 'build queue unavailable' "$c/s.err"
  ck "no traceback" [ "$(grep -c Traceback "$c/s.err")" = 0 ]
  ck "the test ran here" grep -q '^nb-here$' "$c/s.out"
  set -- "$Q"/*.json
  k1 "$1"
}

case_29() {
  mkbq run
  mkdir -p "$Q" && echo '{}' > "$Q/x.json"
  run w zt job submit --wait 30 -- sh -c "echo y >> $c/mark"
  eq "submit --wait beside a foreign file: exit 0" "$rc" 0
  eq "the test ran once" "$(count "$c/mark")" 1
  runse st zt job status
  eq "job status: exit 0" "$rc" 0
  ck "no traceback" [ "$(grep -c Traceback "$c/st.err")" = 0 ]
  ck "no line for the foreign file" [ "$(grep -c '^x' "$c/st.out")" = 0 ]
}

case_30() {
  # this case waits on a real runner process and a FIFO under a 120 s bound, so it is an
  # integration test. zone-tool test-one drops every CODETEAM_* variable (cmd_test_one), so until the shared test
  # command has a group parameter it runs only when called directly:
  #   CODETEAM_TEST_GROUP=integration bash zone/tests/zone-job.sh
  if [ "${CODETEAM_TEST_GROUP:-unit}" != integration ]; then
    echo "skip $cn the hung-runner FIFO read: integration group only; run with CODETEAM_TEST_GROUP=integration" >> "$res/$cn"
    return
  fi
  mkbq fifo-hang
  ZX="CODETEAM_BUILDQ_START_WAIT=120 CODETEAM_BUILDQ_STALE=30"
  # Export the submitter helper so the foreground watchdog also bounds a blocked FIFO read.
  export -f zt
  export P tmp c Q BQ ZX PY ZT here
  runse s /usr/bin/timeout 120 /bin/bash -c 'zt "$@"' _ job submit --wait 30 -- sh -c "cat $Q/*.json > $c/claimed.json; echo hang-here; exit 8"
  ck "the submit hung on the runner state FIFO (exit 124)" [ "$rc" -ne 124 ]
  eq "hung runner: exit is the test's" "$rc" 8
  ck "stderr: build queue unavailable" grep -q 'build queue unavailable' "$c/s.err"
  ck "stderr: runner not responding, not runner not alive" bash -c 'grep -q "the runner is not responding" "$1" && ! grep -q "the runner is not alive" "$1"' _ "$c/s.err"
  ck "the test ran here" grep -q '^hang-here$' "$c/s.out"
  set -- "$Q"/*.json
  ck "its job file ends done, fallback true, exit 8" jx "$1" 'd["state"] == "done" and d["fallback"] is True and d["exit"] == 8'
  k1 "$1"
  ck "the runner served a stale beat" [ -e "$c/hung" ]
}

case_31() {
  mkbq hold-hang
  ZX="CODETEAM_BUILDQ_START_WAIT=120 CODETEAM_BUILDQ_STALE=30"
  run s zt job submit -- true
  tk=$(ticket "$c/s.out")
  if [ "$tk" = none ]; then
    echo "FAIL $cn submit printed a ticket: got [$(cat "$c/s.out")]" >> "$res/$cn"
    return
  fi
  echo "ok   $cn submit printed a ticket" >> "$res/$cn"
  touch "$c/hang"
  ck "the runner published its stale beat" wait_file "$c/hung"
  run w zt job wait "$tk" --max 5
  eq "job wait on a hung runner: exit 4" "$rc" 4
  ck "WAITING: the runner is not responding (last beat N s ago)" grep -Eq '^WAITING: the runner is not responding \(last beat [0-9]+ s ago\)$' "$c/w.out"
  eq "last line names the wait" "$(lastline "$c/w.out")" "WAITING: zone-tool job wait $tk"
}

case_32() {
  eq "no shell limit known: 100" "$(wsec auto)" 100.0
  ZX="BASH_DEFAULT_TIMEOUT_MS=1800000"; eq "30 minutes less 60 s" "$(wsec auto)" 1740.0
  ZX="BASH_DEFAULT_TIMEOUT_MS=200000"; eq "200 s less 60 s" "$(wsec auto)" 140.0
  ZX="BASH_DEFAULT_TIMEOUT_MS=60000"; eq "a short limit: the floor of 30" "$(wsec auto)" 30.0
  ZX=""; eq "a number is itself" "$(wsec 5)" 5.0
  mkbq run
  run w zt job submit --wait auto -- true
  eq "submit --wait auto: exit 0" "$rc" 0
}

case_33() {
  mkbq never
  run s zt job submit -- true
  ck "the submit created Q, 0700" [ "$(pmode "$Q")" = 0o700 ]
  ck "no tmutil call" [ ! -e "$c/tmutil.log" ]
}

case_34() {
  mkbq never
  mkdir -p "$Q"
  run s zt job submit -- true
  eq "submit into an existing queue: exit 0" "$rc" 0
  ck "no tmutil call" [ ! -s "$c/tmutil.log" ]
}

case_35() {
  mkbq never
  run s zt job submit -- true
  tk=$(ticket "$c/s.out"); j="$Q/$tk.json"
  jdone "$j"
  run w zt job wait "$tk" --max 1
  eq "job wait on an answered job: exit 0" "$rc" 0
  eq "the summary: answered from its record" "$(lastline "$c/w.out")" "zone-test: PASS (exit 0); answered from record $(jget "$j" record)"
}

mkdir -p "$tmp/template/pkg" && echo a > "$tmp/template/pkg/a.txt" && echo r > "$tmp/template/README" \
  && git -C "$tmp/template" init -q && git -C "$tmp/template" add -A \
  && git -C "$tmp/template" -c user.email=t@t -c user.name=t commit -qm init
stage="checks running"
for n in $NUMS; do launch "$n" "case_$n"; done
wait

stage="collecting results"
fail=0
failed=""
checks=0
for n in $NUMS; do
  checks=$((checks + 1))
  if [ ! -s "$res/$n" ]; then
    echo "FAIL case $n printed no result"
    fail=1
    failed="$failed $n"
    continue
  fi
  cat "$res/$n"
  if grep -q '^FAIL' "$res/$n"; then
    fail=1
    failed="$failed $n"
    tail -n 3 "$tmp/c$n"/*.out "$tmp/c$n"/*.err 2>/dev/null | sed 's/^/      /'
  fi
done
if [ "$fail" -eq 0 ]; then
  summary="zone-job: all $checks checks ok"
else
  summary="zone-job: FAIL:$failed"
fi
exit $fail
