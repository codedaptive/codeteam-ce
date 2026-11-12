#!/bin/bash
# zone/tests/zone-job-mk.sh: zone.mk's zone-test and zone-test-one submit to the build queue,
# run through make, with the real zone.mk and this checkout's zone-tool, against a fake runner this
# test writes, started through fake-launchctl (zone-job.sh checks the verbs themselves). Each check has its own scratch repo, queue
# and runner, and the checks run side by side. No real runner, no live queue; a stub tmutil first on the PATH
# (zone/docs/TESTING.md), so no check reaches the real Time Machine.
# slow: seven make runs, each with a submit, a runner and the job's own zone-tool test: the last run took 5 s wall, 2.7 s of CPU, at load 42 on 18 CPUs.
# ZONE_MK may be set from outside to run these checks against another zone.mk.
#  01 zone-test-one submits class dev; with ZONE_JOB_WAIT=0 make returns only once the job is done
#     (the summary says PASS, and the job file reads done).
#  02 zone-test-one with CLASS=post submits class post.
#  03 zone-test submits class full.
#  04 ZONE_JOB_WAIT=1 with a runner that never starts: make fails with zone-tool's exit 4 (make prints
#     "Error 4") and prints "WAITING: zone-tool job wait <ticket>".
#  05 a failing test with ZONE_JOB_WAIT=0: make fails with zone-tool's exit 1 and the summary says FAIL.
#  06 no ZONE_JOB_WAIT given (its default, auto, with no shell limit set): make waits for the job and
#     returns its result.
#  07 Time Machine: zone-test-one creates the queue Q and makes no tmutil call.
set -u
unset MAKEFLAGS MFLAGS MAKELEVEL MAKEOVERRIDES MAKEFILES CODETEAM_ZONE CODETEAM_OWNS DIR \
      GIT_DIR GIT_INDEX_FILE GIT_WORK_TREE ZONE ZONE_ROOT ZONE_TOOL ZONE_TEST ZONE_TEST_FLAGS \
      CODETEAM_BUILDQ_TICKET CODETEAM_SLOT_HELD
# Stage 2 (v5.2) sets GROUP and CODETEAM_TEST_GROUP: children must not inherit them or their record keys change.
# export -n keeps the outer values available to this script without exporting them.
export -n GROUP CODETEAM_TEST_GROUP
here="$(cd "$(dirname "$0")/../.." && pwd)"
ZONE_MK="${ZONE_MK:-$here/zone/zone.mk}"
PY=python3
tmp="$(mktemp -d /tmp/zone-job-mk.XXXXXX)"
trap 'kill $(jobs -p) $(cat "$tmp"/c*/pids 2>/dev/null) 2>/dev/null; rm -rf "$tmp"' EXIT
export GIT_CEILING_DIRECTORIES="$tmp"
mkdir -p "$tmp/home"
res="$tmp/results"; mkdir -p "$res"
FAKE="$tmp/fake-runner.py"
NUMS="01 02 03 04 05 06 07"
# Time Machine stub (zone/docs/TESTING.md): a stub tmutil first on the PATH of every make and zone-tool call. It appends its argv to $TMUTIL_LOG and
# exits 0, so no check reaches the real Time Machine.
P="$tmp/stub:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
mkdir -p "$tmp/stub"
cat > "$tmp/stub/tmutil" <<'SH'
#!/bin/sh
echo "$*" >> "$TMUTIL_LOG"
exit 0
SH
chmod +x "$tmp/stub/tmutil"

cat > "$FAKE" <<'PY'
# Fake build-queue runner for zone-job-mk.sh. argv[1]: run (starts queued run jobs, one at a time, and
# finishes each from its record) or never (a fresh heartbeat and no starts).
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
while True:
    write(root / "queue-runner.json", {
        "pid": os.getpid(), "beat": time.time(), "budget": 6, "used": 0,
        "swap": 0.0, "swap_max": 0.9, "swap_hold": False})
    pending = queued()
    if mode == "run":
        if running is None and pending:
            running = start(pending[0])
        elif running is not None and running[1].poll() is not None:
            finish(*running)
            running = None
    if running is not None or pending or mode == "never":
        last_busy = time.time()
    elif idle_exit and time.time() - last_busy >= idle_exit:
        break
    time.sleep(tick)
PY

# make in this check's repo, through zone.mk, with this checkout's zone-tool and the check's queue and runner.
mk() {
  env -i PATH="$P" HOME="$tmp/home" TMPDIR="$tmp" GIT_CEILING_DIRECTORIES="$tmp" MAKEFILES="$ZONE_MK" TMUTIL_LOG="$c/tmutil.log" \
    CODETEAM_HOME="$here" CODETEAM_ZONE=pkg CODETEAM_QUEUE_DIR="$Q" CODETEAM_BUILDQ="$BQ" CODETEAM_BUILDQ_LAUNCH="$here/zone/tests/fake-launchctl" \
    CODETEAM_BUILDQ_TICK=0.05 CODETEAM_BUILDQ_IDLE_EXIT=1 CODETEAM_BUILDQ_START_WAIT=10 CODETEAM_BUILDQ_STALE=2 \
    /usr/bin/make --no-print-directory -C "$R" "$@"
}
mkbq() {  # the runner this check's make starts: a wrapper that records its pid, then runs FAKE in mode $1
  printf '#!/bin/sh\necho $$ >> %s\nexec %s -I %s %s\n' "$c/pids" "$PY" "$FAKE" "$1" > "$BQ"
  chmod +x "$BQ"
}
run()   { local n=$1; shift; "$@" > "$c/$n.out" 2>&1; rc=$?; }
ck()    { local l=$1; shift; if "$@" 2>/dev/null; then echo "ok   $cn $l"; else echo "FAIL $cn $l"; fi >> "$res/$cn"; }
eq()    { if [ "$2" = "$3" ]; then echo "ok   $cn $1"; else echo "FAIL $cn $1: got [$2], want [$3]"; fi >> "$res/$cn"; }
jf()    { "$PY" -I -c 'import json,sys; v=json.load(open(sys.argv[1]))[sys.argv[2]]; print(v if isinstance(v,str) else json.dumps(v))' "$1" "$2"; }

launch() {  # $1 the check's number, $2 its function: a repo (a copy of the template), a queue and a runner of its own
  (
    cn=$1; c="$tmp/c$1"; R="$c/team-x/repo"; Q="$c/run/queue"; BQ="$c/buildq"
    mkdir -p "$c/team-x" && cp -R "$tmp/template" "$R" && cd "$R" || exit 1
    "$2"
    kill $(cat "$c/pids" 2>/dev/null) 2>/dev/null
  ) &
}

case_01() {
  mkbq run
  run m mk zone-test-one DIR=pkg ZONE_TEST_ONE_CMD=true ZONE_JOB_WAIT=0
  eq "make exit 0" "$rc" 0
  ck "the summary: zone-test: PASS (exit 0)" grep -q '^zone-test: PASS (exit 0)' "$c/m.out"
  set -- "$Q"/*.json
  eq "one job, class dev" "$(jf "$1" class)" dev
  eq "the job is done when make returns" "$(jf "$1" state)" done
}

case_02() {
  mkbq run
  run m mk zone-test-one DIR=pkg ZONE_TEST_ONE_CMD=true ZONE_JOB_WAIT=0 CLASS=post
  eq "make exit 0" "$rc" 0
  set -- "$Q"/*.json
  eq "class post" "$(jf "$1" class)" post
}

case_03() {
  mkbq run
  run m mk zone-test ZONE_TEST=true ZONE_JOB_WAIT=0
  eq "make exit 0" "$rc" 0
  set -- "$Q"/*.json
  eq "class full" "$(jf "$1" class)" full
}

case_04() {
  mkbq never
  run m mk zone-test-one DIR=pkg ZONE_TEST_ONE_CMD=true ZONE_JOB_WAIT=1
  ck "make fails" [ "$rc" -ne 0 ]
  ck "make reports zone-tool's exit 4" grep -q 'Error 4' "$c/m.out"
  ck "and prints WAITING: zone-tool job wait <ticket>" grep -Eq 'WAITING: zone-tool job wait [0-9]{8}-[0-9]{6}-[0-9a-f]{6}$' "$c/m.out"
}

case_05() {
  mkbq run
  run m mk zone-test-one DIR=pkg ZONE_TEST_ONE_CMD=false ZONE_JOB_WAIT=0
  ck "make fails" [ "$rc" -ne 0 ]
  ck "make reports zone-tool's exit 1" grep -q 'Error 1' "$c/m.out"
  ck "the summary says FAIL" grep -q '^zone-test: FAIL (exit 1)' "$c/m.out"
}

case_06() {
  mkbq run
  run m mk zone-test-one DIR=pkg ZONE_TEST_ONE_CMD=true
  eq "make exit 0" "$rc" 0
  ck "the summary: zone-test: PASS (exit 0)" grep -q '^zone-test: PASS (exit 0)' "$c/m.out"
}

case_07() {
  mkbq run
  run m mk zone-test-one DIR=pkg ZONE_TEST_ONE_CMD=true ZONE_JOB_WAIT=0
  eq "make exit 0" "$rc" 0
  ck "make creates the queue Q" [ -d "$Q" ]
  ck "no tmutil call" [ ! -e "$c/tmutil.log" ]
}

mkdir -p "$tmp/template/pkg" && echo a > "$tmp/template/pkg/a.txt" \
  && git -C "$tmp/template" init -q && git -C "$tmp/template" add -A \
  && git -C "$tmp/template" -c user.email=t@t -c user.name=t commit -qm init
for n in $NUMS; do launch "$n" "case_$n"; done
wait

fail=0
for n in $NUMS; do
  if [ ! -s "$res/$n" ]; then echo "FAIL case $n printed no result"; fail=1; continue; fi
  cat "$res/$n"
  if grep -q '^FAIL' "$res/$n"; then
    fail=1
    tail -n 3 "$tmp/c$n"/*.out 2>/dev/null | sed 's/^/      /'
  fi
done
exit $fail
