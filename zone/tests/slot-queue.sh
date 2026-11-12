#!/bin/bash
# zone/tests/slot-queue.sh: bin/codeteam-slot waits for the build queue's runner
# (zone/docs/INTERFACE.md). A fake runner (never the live one) holds Q/.runner.lock, keeps a heartbeat in
# run/queue-runner.json and grants slot jobs as the test's control file says. codeteam-slot runs from a copy
# in a scratch folder, so anything it writes beside itself lands in the scratch folder.
# Runner starts requested by codeteam-slot go through fake-launchctl, never the live launchd job.
#  1. The build does not start until the runner marks its job running: the tool starts after the job's
#     `started`, and the job waited for the delay the fake applies.
#  2. A job behind another (position 2): stderr says "The build queue is full" with its place (number 2),
#     then "A build share is free. Starting." when it is granted. A job at position 1 prints no "full".
#  3. No runner running: codeteam-slot starts a runner slow to come alive (over the 0.3 s START_WAIT),
#     waits for it to take the lock, and the build runs.
#  4. A held warm lock does not hold the build: the tool runs within the bound while the lock is held.
#  5. warm_lock is <git dir>/codeteam-warm.lock when that file exists; null when CODETEAM_WARMING=1.
#  6. CODETEAM_JOBS_PER_SLOT=3 sets CARGO_BUILD_JOBS=3; unset, it is 4.
#  7. CODETEAM_BUILDQ=/nonexistent, no runner: stderr "build queue unavailable", the tool runs with exit 7,
#     the job file ends running with fallback true.
#  8. A runner that never comes alive within CODETEAM_BUILDQ_START_WAIT: the same as 7.
#  9. A runner that holds the lock with a stale heartbeat: the same as 7.
# 10. Compare-and-swap: the runner marks the job running and then its heartbeat goes stale: the job's
#     fallback stays not true (it is not re-marked fallback) and the tool runs with exit 7.
# 11. Q unwritable: stderr "build queue unavailable", the tool runs with exit 7, no job file is written.
# 12. /usr/bin/python3 runs the copy: a build runs through it (exit 7, a slot job file), and bin/codeteam-slot
#     parses with ast at feature_version (3, 9).
# 13. No run/slots directory is created by a run.
# 14. A job held for a warm (the job file's hold is "warm"): stderr says "This worktree is still being warmed"
#     once, then "A build share is free. Starting." when it is granted, and the tool runs.
# 15. The runner codeteam-slot starts is never a descendant of the build: its ppid is 1, and killing the build's
#     whole tree (the tool and its children) leaves the runner alive.
# 16. env: a job the fallback claims when the runner never came alive keeps env {} (it is running, fallback true).
# 17. env: a queued slot job has env {} while the runner holds it.
# 18. env: a job the fallback claims after a stale heartbeat keeps env {} (it is running, fallback true).
# Integration group only: 1-6, 8-10, 12, 14-18.
# slow: integration checks start runner subprocesses and include deliberate waits (a 0.5 s grant delay,
# a 0.3 s START_WAIT, a 1 s slow start in case 3, and runner stops and starts). Load can extend runtime;
# generous deadlines limit waits without making successful runs wait for the full bounds.
set -u
# Stage 2 (v5.2) sets GROUP and CODETEAM_TEST_GROUP: children must not inherit them or their record keys change.
# export -n keeps the outer values available to this script without exporting them.
export -n GROUP CODETEAM_TEST_GROUP
here="$(cd "$(dirname "$0")/../.." && pwd)"
py=python3
tmp="$(cd "$(mktemp -d)" && pwd -P)"
Q="$tmp/run/queue"
trap 'for p in $(cat "$tmp/fake/pids" "$tmp/fake/holder" 2>/dev/null); do kill "$p" 2>/dev/null; done; chmod -R u+w "$Q" 2>/dev/null; rm -rf "$tmp"' EXIT
path="$tmp/stub:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
fail=0
ok()  { echo "ok   $1"; }
bad() { echo "FAIL $1: $2"; fail=1; }

# tm_stub DIR EXIT: a stub tmutil in DIR that appends its argv to $tmp/tm.log and exits EXIT. Every PATH here puts a stub
# ahead of /usr/bin, so no run touches the real Time Machine.
tm_stub() {
  printf '#!/bin/sh\necho "$*" >> "%s"\nexit %s\n' "$tmp/tm.log" "$2" > "$1/tmutil"
  chmod +x "$1/tmutil"
}

proj="$tmp/team-x/proj"
mkdir -p "$proj" "$tmp/stub" "$tmp/fake" "$tmp/bin" "$Q"
chmod 700 "$Q"
git -C "$proj" init -q
gitdir="$(git -C "$proj" rev-parse --path-format=absolute --git-dir)"
# The tool stand-in: its pid, the session flag, the jobs count, and its start time (epoch, from python).
printf '#!/bin/sh\necho "pid=$$"\necho "held=${CODETEAM_SLOT_HELD:-unset}"\necho "jobs=${CARGO_BUILD_JOBS:-unset}"\necho "t=$(%s -c "import time; print(time.time())")"\nexit 7\n' "$py" > "$tmp/stub/cargo"
chmod +x "$tmp/stub/cargo"
tm_stub "$tmp/stub" 0
# A dead runner: exits at once, never takes the lock.
printf '#!/bin/sh\nexit 0\n' > "$tmp/fake/dead"
chmod +x "$tmp/fake/dead"

# The fake runner. Its control file (FAKE_CTL) is read at every tick: hold (tickets it leaves queued, "*" for all),
# delay (seconds after submit before a grant), warm (true: the jobs it holds get hold "warm"), beat ("stale" makes the heartbeat old), stale_after_flip (the
# heartbeat goes stale once it has granted a job). It takes Q/.runner.lock or exits; it writes its pid to FAKE_PIDS.
cat > "$tmp/fake/runner" <<'PY'
#!/usr/bin/env python3
import fcntl, json, os, time
q = os.environ["CODETEAM_QUEUE_DIR"]
lock = open(os.path.join(q, ".runner.lock"), "a+")
import time as _t
_deadline = _t.monotonic() + 0.5
while True:   # a client probe (brief LOCK_NB) may hold it for an instant: retry, as bin/codeteam-buildq does
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        break
    except BlockingIOError:
        if _t.monotonic() >= _deadline:
            raise SystemExit(0)
        _t.sleep(0.02)
with open(os.environ["FAKE_PIDS"], "a") as f:
    f.write(f"{os.getpid()}\n")
with open(os.environ["FAKE_MARK"], "a") as f:
    f.write("started\n")
state = os.path.join(q, "..", "queue-runner.json")
stale = False
def write_json(path, obj):
    with open(path + ".tmp", "w") as f:
        json.dump(obj, f)
    os.replace(path + ".tmp", path)
while True:
    try:
        ctl = json.load(open(os.environ["FAKE_CTL"]))
    except (OSError, ValueError):
        ctl = {}
    stale = stale or ctl.get("beat") == "stale"
    hold = ctl.get("hold", [])
    want = "warm" if ctl.get("warm") else None
    now = time.time()
    flipped = False
    with open(os.path.join(q, ".lock"), "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        queued = []
        for name in os.listdir(q):
            if not name.endswith(".json") or name.startswith("."):
                continue
            p = os.path.join(q, name)
            try:
                job = json.load(open(p))
            except (OSError, ValueError):
                continue
            if job.get("kind") == "slot" and job.get("state") == "queued":
                queued.append((job.get("submitted", 0), p, job))
        for place, (submitted, p, job) in enumerate(sorted(queued, key=lambda e: e[0]), 1):
            ticket = os.path.basename(p)[:-5]
            granted = ("*" not in hold and ticket not in hold) and now >= submitted + ctl.get("delay", 0)
            if granted:
                job.update(state="running", started=now, position=None, hold=None)
                flipped = True
            elif job.get("position") != place or job.get("hold") != want:
                job.update(position=place, hold=want)
            else:
                continue
            write_json(p, job)
    if flipped and ctl.get("stale_after_flip"):
        stale = True
    write_json(state, {"pid": os.getpid(), "beat": 1.0 if stale else time.time()})
    time.sleep(0.05)
PY
chmod +x "$tmp/fake/runner"

# A runner that takes longer than ENVBASE's 0.3 s START_WAIT to come alive.
# Record its pid before sleeping so stop_runner can kill it during the delay.
cat > "$tmp/fake/slow" <<'SH'
#!/bin/sh
echo "$$" >> "$FAKE_PIDS"
sleep 1
exec "$(dirname "$0")/runner"
SH
chmod +x "$tmp/fake/slow"

# set_ctl JSON: the fake's control file, replaced atomically.
set_ctl() { printf '%s' "$1" > "$tmp/fake/ctl.tmp" && mv "$tmp/fake/ctl.tmp" "$tmp/fake/ctl"; }

# start_runner JSON: start the fake with that control and poll for its heartbeat until the deadline.
start_runner() {
  set_ctl "$1"
  env CODETEAM_QUEUE_DIR="$Q" FAKE_CTL="$tmp/fake/ctl" FAKE_PIDS="$tmp/fake/pids" FAKE_MARK="$tmp/fake/mark" \
    "$tmp/fake/runner" >/dev/null 2>&1 &
  local end=$((SECONDS + 60))
  until [ -s "$tmp/run/queue-runner.json" ] || [ "$SECONDS" -ge "$end" ]; do sleep 0.05; done
}

# stop_runner: signal recorded fake runners and poll for a free lock until the deadline.
stop_runner() {
  for p in $(cat "$tmp/fake/pids" 2>/dev/null); do kill "$p" 2>/dev/null; done
  : > "$tmp/fake/pids"
  local end=$((SECONDS + 60))
  until "$py" -I -c 'import fcntl, sys
f = open(sys.argv[1], "a+")
fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)' "$Q/.runner.lock" 2>/dev/null || [ "$SECONDS" -ge "$end" ]; do
    sleep 0.05
  done
  rm -f "$tmp/run/queue-runner.json"
}

# job_field JOB_FILE FIELD: the field as JSON, <missing>, or <unreadable>.
job_field() {
  "$py" -I -c 'import json, sys
print(json.dumps(json.load(open(sys.argv[1])).get(sys.argv[2], "<missing>")))' "$1" "$2" 2>/dev/null || echo "<unreadable>"
}

# newest_job: the job file in Q with the latest submitted time, or nothing.
newest_job() {
  "$py" -I -c 'import glob, json, sys
jobs = [(json.load(open(p)).get("submitted") or 0, p) for p in glob.glob(sys.argv[1] + "/*.json")]
print(max(jobs)[1] if jobs else "")' "$Q" 2>/dev/null
}

# Outer bounds and event polls use generous wall-clock deadlines so load is far less likely to fail a check.
# Bounded runs and event polls check for process exit or the event between sleeps.
# Keep the short timings the checks need: START_WAIT 0.3 s (8, 16), STALE 2 s (9, 10, 18),
# the 0.5 s grant delay (1), and the fake runner's 0.5 s lock retry (a loser must not acquire it later unrecorded).
# bounded SECONDS OUT ERR DIR CMD...: run CMD in DIR with output in OUT and ERR; signal it if still alive
# when the deadline is reached. Bash SECONDS has one-second resolution; checks can also be delayed by load.
bounded() {
  local secs="$1" out="$2" err="$3" dir="$4"
  shift 4
  local end=$((SECONDS + secs))
  (cd "$dir" && exec "$@") >"$out" 2>"$err" &
  local pid=$!
  while kill -0 "$pid" 2>/dev/null && [ "$SECONDS" -lt "$end" ]; do sleep 0.05; done
  if kill -0 "$pid" 2>/dev/null; then kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null; return 124; fi
  wait "$pid"
}

# slot_run OUT ERR DIR ARGS...: codeteam-slot in DIR with the stub PATH; EXTRA (set by the check) adds variables.
ENVBASE="PATH=$path HOME=$HOME GIT_CEILING_DIRECTORIES=$tmp CODETEAM_QUEUE_DIR=$Q CODETEAM_BUILDQ_LAUNCH=$here/zone/tests/fake-launchctl CODETEAM_BUILDQ=$tmp/fake/runner CODETEAM_BUILDQ_TICK=0.05 CODETEAM_BUILDQ_START_WAIT=0.3 CODETEAM_BUILDQ_STALE=2 FAKE_CTL=$tmp/fake/ctl FAKE_PIDS=$tmp/fake/pids FAKE_MARK=$tmp/fake/mark"
EXTRA=""
slot_run() {
  local out="$1" err="$2" dir="$3"
  shift 3
  bounded 120 "$out" "$err" "$dir" env -i $ENVBASE $EXTRA "$slot" "$@"
}

slot="$tmp/bin/codeteam-slot"
cp "$here/bin/codeteam-slot" "$slot"
chmod +x "$slot"

# runner processes and clock waits belong to integration.
# Run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/slot-queue.sh
if [ "${CODETEAM_TEST_GROUP:-unit}" = integration ]; then
# 1. The grant: a delayed grant; the tool starts after the job's started.
start_runner '{"hold":[],"delay":0.5}'
EXTRA="CODETEAM_SESSION=s1"
slot_run "$tmp/c1.out" "$tmp/c1.err" "$proj" cargo build; rc=$?
jf="$(newest_job)"
t_tool="$(sed -n 's/^t=//p' "$tmp/c1.out")"
started="$(job_field "$jf" started)"; submitted="$(job_field "$jf" submitted)"
if [ "$rc" = 7 ] && [ -n "$jf" ] && [ -n "$t_tool" ] \
   && "$py" -I -c 'import sys
t, s, b = map(float, sys.argv[1:4])
sys.exit(0 if t >= s and s - b >= 0.4 else 1)' "$t_tool" "$started" "$submitted" 2>/dev/null; then
  ok "the tool starts after the runner grants the job (not before)"
else bad "the tool starts after the runner grants the job (not before)" "exit $rc, tool t [$t_tool], started $started, submitted $submitted"; fi

# 2. A job at position 2 waits behind a held job.
set_ctl '{"hold":["*"],"delay":0}'
printf '%s' '{"ticket":"seeded-a","kind":"slot","class":"dev","state":"queued","submitted":1,"pid":1,"team":"team-y","session":null,"worktree":null,"tool":"cargo","command":["cargo","build"],"key":"slot cargo","env":{},"record":null,"test_flags":[],"warm_lock":null,"reason":null,"cost":1,"exit":null,"result":null,"record_mtime":null,"finished":null,"started":null,"estimated_start":null,"position":1,"fallback":false}' > "$Q/seeded-a.json"
EXTRA="CODETEAM_SESSION=s1"
bounded 120 "$tmp/c2.out" "$tmp/c2.err" "$proj" env -i $ENVBASE "$slot" cargo build &
b2=$!
end=$((SECONDS + 60)); until grep -q 'queue is full' "$tmp/c2.err" 2>/dev/null || [ "$SECONDS" -ge "$end" ]; do sleep 0.05; done
set_ctl '{"hold":[],"delay":0}'
wait "$b2"; rc=$?
if [ "$rc" = 7 ] && grep -q 'The build queue is full.*number 2' "$tmp/c2.err" \
   && grep -q 'A build share is free. Starting.' "$tmp/c2.err" && grep -q '^pid=' "$tmp/c2.out"; then
  ok "position 2 prints the full message with its place, then the free message, then runs"
else bad "position 2 prints the full message with its place, then the free message, then runs" "exit $rc, stderr [$(cat "$tmp/c2.err")]"; fi
rm -f "$Q/seeded-a.json"    # the later checks read only the job files their own runs wrote

# 3. No runner running: codeteam-slot starts the slow CODETEAM_BUILDQ wrapper.
stop_runner
: > "$tmp/fake/mark"
EXTRA="CODETEAM_BUILDQ=$tmp/fake/slow"
# Allow 120 s for startup under load ~150; ensure_runner returns when it detects the runner's lock.
# Bound the whole run at 150 s to leave time for the build after startup.
bounded 150 "$tmp/c3.out" "$tmp/c3.err" "$proj" env -i $ENVBASE $EXTRA CODETEAM_BUILDQ_START_WAIT=120 "$slot" cargo build; rc=$?
if [ "$rc" = 7 ] && grep -q '^started$' "$tmp/fake/mark" && grep -q '^pid=' "$tmp/c3.out"; then
  ok "no runner running: codeteam-slot starts the runner and the build runs"
else bad "no runner running: codeteam-slot starts the runner and the build runs" "exit $rc, mark [$(cat "$tmp/fake/mark" 2>/dev/null)], stderr [$(cat "$tmp/c3.err")]"; fi

# 4. A held warm lock does not hold the build. Keep the holder alive beyond the run's bound.
stop_runner
start_runner '{"hold":[],"delay":0}'
: > "$gitdir/codeteam-warm.lock"
"$py" -I -c 'import fcntl, sys, time
f = open(sys.argv[1], "a+")
fcntl.flock(f, fcntl.LOCK_EX)
print("held", flush=True)
time.sleep(600)' "$gitdir/codeteam-warm.lock" >"$tmp/holder.out" 2>&1 &
echo $! > "$tmp/fake/holder"
end=$((SECONDS + 60)); until grep -q '^held' "$tmp/holder.out" 2>/dev/null || [ "$SECONDS" -ge "$end" ]; do sleep 0.05; done
EXTRA=""
slot_run "$tmp/c4.out" "$tmp/c4.err" "$proj" cargo build; rc=$?
if [ "$rc" = 7 ] && grep -q '^pid=' "$tmp/c4.out"; then
  ok "a held warm lock does not hold the build: the tool runs at once"
else bad "a held warm lock does not hold the build: the tool runs at once" "exit $rc, stdout [$(cat "$tmp/c4.out")], stderr [$(cat "$tmp/c4.err")]"; fi

# 5. warm_lock: the git dir's lock file, null when CODETEAM_WARMING=1.
jf="$(newest_job)"
got="$(job_field "$jf" warm_lock)"
EXTRA="CODETEAM_WARMING=1"
slot_run "$tmp/c5.out" "$tmp/c5.err" "$proj" cargo build
jw="$(newest_job)"
if [ "$got" = "\"$gitdir/codeteam-warm.lock\"" ] && [ "$(job_field "$jw" warm_lock)" = null ]; then
  ok "warm_lock is the git dir's lock file, null under CODETEAM_WARMING=1"
else bad "warm_lock is the git dir's lock file, null under CODETEAM_WARMING=1" "warm_lock [$got], warming job [$(job_field "$jw" warm_lock)]"; fi
kill "$(cat "$tmp/fake/holder")" 2>/dev/null
rm -f "$gitdir/codeteam-warm.lock"

# 6. CODETEAM_JOBS_PER_SLOT sets CARGO_BUILD_JOBS.
EXTRA="CODETEAM_JOBS_PER_SLOT=3"
slot_run "$tmp/c6.out" "$tmp/c6.err" "$proj" cargo build
three="$(sed -n 's/^jobs=//p' "$tmp/c6.out")"
EXTRA=""
slot_run "$tmp/c6b.out" "$tmp/c6b.err" "$proj" cargo build
four="$(sed -n 's/^jobs=//p' "$tmp/c6b.out")"
if [ "$three" = 3 ] && [ "$four" = 4 ]; then ok "CODETEAM_JOBS_PER_SLOT sets CARGO_BUILD_JOBS (3), default 4"
else bad "CODETEAM_JOBS_PER_SLOT sets CARGO_BUILD_JOBS (3), default 4" "jobs [$three] and [$four]"; fi
else
  echo "skip 1 the tool starts after the runner grants the job (not before): integration group only; run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/slot-queue.sh"
  echo "skip 2 position 2 prints the full message with its place, then the free message, then runs: integration group only; run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/slot-queue.sh"
  echo "skip 3 no runner running: codeteam-slot starts the runner and the build runs: integration group only; run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/slot-queue.sh"
  echo "skip 4 a held warm lock does not hold the build: the tool runs at once: integration group only; run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/slot-queue.sh"
  echo "skip 5 warm_lock is the git dir's lock file, null under CODETEAM_WARMING=1: integration group only; run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/slot-queue.sh"
  echo "skip 6 CODETEAM_JOBS_PER_SLOT sets CARGO_BUILD_JOBS (3), default 4: integration group only; run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/slot-queue.sh"
fi

# Fallbacks (7, 8): no runner comes alive.
fallback_check() {
  local label="$1" n="$2"
  if [ "${CODETEAM_TEST_GROUP:-unit}" = integration ]; then stop_runner; fi
  EXTRA="CODETEAM_SESSION=s1 $3"
  slot_run "$tmp/f$n.out" "$tmp/f$n.err" "$proj" cargo build; rc=$?
  jf="$(newest_job)"
  if [ "$rc" = 7 ] && grep -q 'build queue unavailable' "$tmp/f$n.err" && grep -q '^pid=' "$tmp/f$n.out" \
     && [ "$(job_field "$jf" state)" = '"running"' ] && [ "$(job_field "$jf" fallback)" = true ]; then
    ok "$label"
  else bad "$label" "exit $rc, stderr [$(cat "$tmp/f$n.err")], job [$jf] state $(job_field "$jf" state) fallback $(job_field "$jf" fallback)"; fi
}
fallback_check "CODETEAM_BUILDQ=/nonexistent: build queue unavailable, the tool runs, job fallback true" 7 \
  "CODETEAM_BUILDQ=/nonexistent"
if [ "${CODETEAM_TEST_GROUP:-unit}" = integration ]; then
fallback_check "a runner that never comes alive: build queue unavailable, the tool runs, job fallback true" 8 \
  "CODETEAM_BUILDQ=$tmp/fake/dead"

# 9. A stale heartbeat: the lock is held, the heartbeat is old.
start_runner '{"hold":["*"],"beat":"stale"}'
EXTRA="CODETEAM_SESSION=s1"
slot_run "$tmp/c9.out" "$tmp/c9.err" "$proj" cargo build; rc=$?
jf="$(newest_job)"
if [ "$rc" = 7 ] && grep -q 'build queue unavailable' "$tmp/c9.err" && grep -q '^pid=' "$tmp/c9.out" \
   && [ "$(job_field "$jf" state)" = '"running"' ] && [ "$(job_field "$jf" fallback)" = true ]; then
  ok "a stale heartbeat: build queue unavailable, the tool runs, job fallback true"
else bad "a stale heartbeat: build queue unavailable, the tool runs, job fallback true" "exit $rc, stderr [$(cat "$tmp/c9.err")], job [$jf]"; fi

# 10. Compare-and-swap: the runner grants the job, then its heartbeat goes stale.
stop_runner
start_runner '{"hold":[],"delay":0,"stale_after_flip":true}'
EXTRA="CODETEAM_SESSION=s1"
slot_run "$tmp/c10.out" "$tmp/c10.err" "$proj" cargo build; rc=$?
jf="$(newest_job)"
if [ "$rc" = 7 ] && grep -q '^pid=' "$tmp/c10.out" && [ "$(job_field "$jf" state)" = '"running"' ] \
   && [ "$(job_field "$jf" fallback)" != true ]; then
  ok "a job the runner already granted is not re-marked fallback; the tool runs, exit 7"
else bad "a job the runner already granted is not re-marked fallback; the tool runs, exit 7" "exit $rc, job [$jf] fallback $(job_field "$jf" fallback), stderr [$(cat "$tmp/c10.err")]"; fi

stop_runner
else
  echo "skip 8 a runner that never comes alive: build queue unavailable, the tool runs, job fallback true: integration group only; run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/slot-queue.sh"
  echo "skip 9 a stale heartbeat: build queue unavailable, the tool runs, job fallback true: integration group only; run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/slot-queue.sh"
  echo "skip 10 a job the runner already granted is not re-marked fallback; the tool runs, exit 7: integration group only; run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/slot-queue.sh"
fi

# 11. Q unwritable: no job file, the tool runs.
before="$(ls "$Q" | wc -l | tr -d ' ')"
chmod 500 "$Q"
EXTRA="CODETEAM_SESSION=s1"
slot_run "$tmp/c11.out" "$tmp/c11.err" "$proj" cargo build; rc=$?
after="$(ls "$Q" | wc -l | tr -d ' ')"
chmod 700 "$Q"
if [ "$rc" = 7 ] && grep -q 'build queue unavailable' "$tmp/c11.err" && grep -q '^pid=' "$tmp/c11.out" && [ "$before" = "$after" ]; then
  ok "unwritable Q: build queue unavailable, the tool runs, exit 7, no job file"
else bad "unwritable Q: build queue unavailable, the tool runs, exit 7, no job file" "exit $rc, stderr [$(cat "$tmp/c11.err")], files before $before after $after"; fi

if [ "${CODETEAM_TEST_GROUP:-unit}" = integration ]; then
# 12. Python 3.9: the copy runs under /usr/bin/python3, and the file parses at feature_version (3, 9).
start_runner '{"hold":[],"delay":0}'
EXTRA="CODETEAM_SESSION=s1"
bounded 120 "$tmp/c12.out" "$tmp/c12.err" "$proj" env -i $ENVBASE /usr/bin/python3 "$slot" cargo build; rc=$?
jf="$(newest_job)"
parse="$(/usr/bin/python3 -c 'import ast, sys
ast.parse(open(sys.argv[1]).read(), feature_version=(3, 9))
print("parsed")' "$here/bin/codeteam-slot" 2>&1)"
if [ "$rc" = 7 ] && grep -q '^pid=' "$tmp/c12.out" && [ -n "$jf" ] && [ "$parse" = parsed ]; then
  ok "/usr/bin/python3 runs a gated build (exit 7, a slot job) and the file parses at (3, 9)"
else bad "/usr/bin/python3 runs a gated build (exit 7, a slot job) and the file parses at (3, 9)" "exit $rc, job [$jf], parse [$parse], stderr [$(cat "$tmp/c12.err")]"; fi

else
  echo "skip 12 /usr/bin/python3 runs a gated build (exit 7, a slot job) and the file parses at (3, 9): integration group only; run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/slot-queue.sh"
fi

# 13. Neither the fallback run in 7 nor the unwritable-queue run in 11 creates run/slots.
if [ ! -e "$tmp/run/slots" ]; then ok "no run/slots folder is created"
else bad "no run/slots folder is created" "$tmp/run/slots exists"; fi

if [ "${CODETEAM_TEST_GROUP:-unit}" = integration ]; then
# 14. A job held for the warm.
stop_runner
start_runner '{"hold":["*"],"warm":true}'
EXTRA="CODETEAM_SESSION=s1"
bounded 120 "$tmp/c14.out" "$tmp/c14.err" "$proj" env -i $ENVBASE $EXTRA "$slot" cargo build &
b14=$!
end=$((SECONDS + 60)); until grep -q 'still being warmed' "$tmp/c14.err" 2>/dev/null || [ "$SECONDS" -ge "$end" ]; do sleep 0.05; done
sleep 0.3
set_ctl '{"hold":[],"delay":0}'
wait "$b14"; rc=$?
if [ "$rc" = 7 ] && [ "$(grep -c 'still being warmed' "$tmp/c14.err")" = 1 ] \
   && grep -q 'A build share is free. Starting.' "$tmp/c14.err" && grep -q '^pid=' "$tmp/c14.out"; then
  ok "hold warm: the warm message once, then the start message, then the tool runs"
else bad "hold warm: the warm message once, then the start message, then the tool runs" "exit $rc, stderr [$(cat "$tmp/c14.err")]"; fi

# 15. The runner codeteam-slot starts is not the build's descendant. The tool is a long sleep with the tool's pid.
stop_runner
mkdir -p "$tmp/stub2"
printf '#!/bin/sh\necho "pid=$$"\nexec sleep 600\n' > "$tmp/stub2/cargo"
chmod +x "$tmp/stub2/cargo"
tm_stub "$tmp/stub2" 0
set_ctl '{"hold":[],"delay":0}'
: > "$tmp/fake/pids"
(cd "$proj" && exec env -i $ENVBASE CODETEAM_BUILDQ_START_WAIT=120 PATH="$tmp/stub2:$path" "$slot" cargo build) >"$tmp/c15.out" 2>"$tmp/c15.err" &
b15=$!
# 150 s: the run's 120 s START_WAIT plus time for the grant and the tool's pid line.
end=$((SECONDS + 150)); until grep -q '^pid=' "$tmp/c15.out" 2>/dev/null && [ -s "$tmp/fake/pids" ] || [ "$SECONDS" -ge "$end" ]; do sleep 0.05; done
tool_pid="$(sed -n 's/^pid=//p' "$tmp/c15.out")"
runner="$(head -n 1 "$tmp/fake/pids")"
ppid="$(ps -o ppid= -p "${runner:-0}" 2>/dev/null | tr -d ' ')"
if [ -n "$tool_pid" ]; then
  pkill -P "$tool_pid" 2>/dev/null
  kill "$tool_pid" 2>/dev/null
else
  # No tool pid arrived: signal the background run and its direct children so waiting need not outlast the stub.
  pkill -P "$b15" 2>/dev/null
  kill "$b15" 2>/dev/null
fi
wait "$b15" 2>/dev/null
sleep 0.3
if [ -n "$tool_pid" ] && [ -n "$runner" ] && [ "$ppid" = 1 ] && kill -0 "$runner" 2>/dev/null; then
  ok "the runner the build started has ppid 1 and survives a kill of the build's tree"
else bad "the runner the build started has ppid 1 and survives a kill of the build's tree" "tool $tool_pid, runner [$runner], runner ppid [$ppid], alive $(kill -0 "${runner:-0}" 2>&1 && echo yes || echo no)"; fi

# 16. env: the runner never came alive, the fallback claims the job: the job keeps env {}.
stop_runner
EXTRA="CODETEAM_SESSION=s1 CODETEAM_BUILDQ=$tmp/fake/dead"
slot_run "$tmp/c16.out" "$tmp/c16.err" "$proj" cargo build; rc=$?
jf="$(newest_job)"
if [ "$rc" = 7 ] && grep -q 'build queue unavailable' "$tmp/c16.err" && grep -q '^pid=' "$tmp/c16.out" \
   && [ "$(job_field "$jf" state)" = '"running"' ] && [ "$(job_field "$jf" fallback)" = true ] \
   && [ "$(job_field "$jf" env)" = '{}' ]; then
  ok "a fallback claim on a runner that never came alive keeps the job's env {}"
else bad "a fallback claim on a runner that never came alive keeps the job's env {}" "exit $rc, job [$jf], env $(job_field "$jf" env), state $(job_field "$jf" state), fallback $(job_field "$jf" fallback)"; fi

# 17. env: a queued slot job still has env {} while the runner holds it.
stop_runner
start_runner '{"hold":["*"],"delay":0}'
EXTRA="CODETEAM_SESSION=s1"
bounded 120 "$tmp/c17.out" "$tmp/c17.err" "$proj" env -i $ENVBASE $EXTRA "$slot" cargo build &
b17=$!
end=$((SECONDS + 60)); until [ "$(job_field "$(newest_job)" state)" = '"queued"' ] && [ "$(job_field "$(newest_job)" position)" = 1 ] || [ "$SECONDS" -ge "$end" ]; do sleep 0.05; done
jf="$(newest_job)"
queued_env="$(job_field "$jf" env)"
set_ctl '{"hold":[],"delay":0}'
wait "$b17"; rc=$?
if [ "$rc" = 7 ] && [ "$queued_env" = '{}' ]; then
  ok "a queued slot job has env {} while the runner holds it"
else bad "a queued slot job has env {} while the runner holds it" "exit $rc, job [$jf], queued env [$queued_env], stderr [$(cat "$tmp/c17.err")]"; fi

# 18. env: a stale heartbeat, the fallback claims the job: the job keeps env {}.
stop_runner
start_runner '{"hold":["*"],"beat":"stale"}'
EXTRA="CODETEAM_SESSION=s1"
slot_run "$tmp/c18.out" "$tmp/c18.err" "$proj" cargo build; rc=$?
jf="$(newest_job)"
if [ "$rc" = 7 ] && grep -q 'build queue unavailable' "$tmp/c18.err" && grep -q '^pid=' "$tmp/c18.out" \
   && [ "$(job_field "$jf" state)" = '"running"' ] && [ "$(job_field "$jf" fallback)" = true ] \
   && [ "$(job_field "$jf" env)" = '{}' ]; then
  ok "a fallback claim after a stale heartbeat keeps the job's env {}"
else bad "a fallback claim after a stale heartbeat keeps the job's env {}" "exit $rc, job [$jf], env $(job_field "$jf" env), state $(job_field "$jf" state), fallback $(job_field "$jf" fallback)"; fi

stop_runner
else
  echo "skip 14 hold warm: the warm message once, then the start message, then the tool runs: integration group only; run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/slot-queue.sh"
  echo "skip 15 the runner the build started has ppid 1 and survives a kill of the build's tree: integration group only; run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/slot-queue.sh"
  echo "skip 16 a fallback claim on a runner that never came alive keeps the job's env {}: integration group only; run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/slot-queue.sh"
  echo "skip 17 a queued slot job has env {} while the runner holds it: integration group only; run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/slot-queue.sh"
  echo "skip 18 a fallback claim after a stale heartbeat keeps the job's env {}: integration group only; run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/slot-queue.sh"
fi
exit $fail
