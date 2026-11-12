#!/bin/bash
# zone/tests/slot-record.sh: bin/codeteam-slot submits a slot job (kind "slot", class "dev") to the build
# queue . The job file is the
# record the deck reads: its pid is the tool's (execv keeps it), its worktree, team and session come from
# the build's folder and CODETEAM_SESSION. Checks 1-4 are integration-only: they poll until a
# separately started fake-runner process grants the job. Any runner start requested by codeteam-slot
# goes through fake-launchctl, never the live launchd job.
# Run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/slot-record.sh.
#  1. A gated `cargo build` from a team-x worktree writes Q/<ticket>.json: kind "slot", class "dev", pid
#     the tool's, team "team-x", session "s1", worktree the git top level, tool "cargo", command
#     ["cargo","build"], key "slot cargo", env {} (written at submit, and kept once the fake runner grants
#     the job), submitted now, file mode 0600.
#     The tool runs with its output and exit 7.
#  2. CODETEAM_SESSION unset: session null.
#  3. A gated build from a folder outside any git repo: worktree and team null. Exit 7.
#  4. A git that exits 1 on PATH: worktree and team null. Exit 7.
#  5. An ungated `cargo --version` writes no job file and exits 7.
#  6. CODETEAM_SLOT_HELD=1 on a gated build: no job file, exit 7, the tool sees CODETEAM_SLOT_HELD.
#  7. CODETEAM_BUILDQ_TICKET=x on a gated build: no job file, exit 7, the tool runs.
#  8. Time Machine: a gated build that creates Q (no Q before) makes no tmutil call, and Q is created 0700.
#  9. Time Machine: a gated build on an existing Q makes no tmutil call.
# Checks 5 to 7 run with no runner (CODETEAM_BUILDQ=/nonexistent) and guard that a call which needs no turn
# (ungated, or already holding one) writes no job. An unexpected submission falls back at once but fails the no-job check.
# Checks 8 and 9 run with no runner (CODETEAM_BUILDQ=/nonexistent): the build falls back at once, and only Q's
# creation is under test. Every PATH here starts with a stub tmutil (zone/docs/TESTING.md): no run reaches the real Time Machine.
set -u
# Stage 2 (v5.2) sets GROUP and CODETEAM_TEST_GROUP: children must not inherit them or their record keys change.
# export -n keeps the outer values available to this script without exporting them.
export -n GROUP CODETEAM_TEST_GROUP
here="$(cd "$(dirname "$0")/../.." && pwd)"
slot="$here/bin/codeteam-slot"
py=python3
tmp="$(cd "$(mktemp -d)" && pwd -P)"
runner_pid=""
trap 'kill "$runner_pid" 2>/dev/null; rm -rf "$tmp"' EXIT
path="$tmp/stub:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
fail=0
ok()  { echo "ok   $1"; }
bad() { echo "FAIL $1: $2"; fail=1; }

# tm_stub DIR EXIT: a stub tmutil in DIR that appends its argv to $tmp/tm.log and exits EXIT.
tm_stub() {
  printf '#!/bin/sh\necho "$*" >> "%s"\nexit %s\n' "$tmp/tm.log" "$2" > "$1/tmutil"
  chmod +x "$1/tmutil"
}

proj="$tmp/team-x/proj"
plain="$tmp/team-x/plain"
Q="$tmp/run/queue"
mkdir -p "$proj" "$plain" "$tmp/stub" "$tmp/gitstub" "$tmp/fake"
git -C "$proj" init -q
# The tool stand-in: prints its pid, the session-held flag, the ticket, then exits 7.
printf '#!/bin/sh\necho "pid=$$"\necho "held=${CODETEAM_SLOT_HELD:-unset}"\necho "ticket=${CODETEAM_BUILDQ_TICKET:-unset}"\nexit 7\n' > "$tmp/stub/cargo"
printf '#!/bin/sh\nexit 1\n' > "$tmp/gitstub/git"
chmod +x "$tmp/stub/cargo" "$tmp/gitstub/git"
tm_stub "$tmp/stub" 0
tm_stub "$tmp/gitstub" 0

# The fake runner: holds Q/.runner.lock, keeps a fresh heartbeat in run/queue-runner.json and marks every
# queued slot job running at once. It never reads or writes the live codeteam checkout's run/ folder.
cat > "$tmp/fake/runner.py" <<'PY'
import fcntl, json, os, sys, time
q = sys.argv[1]
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
state = os.path.join(q, "..", "queue-runner.json")
while True:
    with open(state + ".tmp", "w") as f:
        json.dump({"pid": os.getpid(), "beat": time.time()}, f)
    os.replace(state + ".tmp", state)
    for name in os.listdir(q):
        if not name.endswith(".json") or name.startswith("."):
            continue
        p = os.path.join(q, name)
        job = json.load(open(p))
        if job.get("kind") == "slot" and job.get("state") == "queued":
            job.update(state="running", started=time.time(), position=None)
            with open(p + ".tmp", "w") as f:
                json.dump(job, f)
            os.replace(p + ".tmp", p)
    time.sleep(0.05)
PY

# job_field JOB_FILE FIELD: one field of a job file as JSON, or <missing>.
job_field() {
  "$py" -I -c 'import json, sys
job = json.load(open(sys.argv[1]))
print(json.dumps(job.get(sys.argv[2], "<missing>")))' "$1" "$2" 2>/dev/null || echo "<unreadable>"
}

# The first slot job file in Q, or nothing.
job_file() { ls "$Q"/*.json 2>/dev/null | head -n 1; }

# start_runner: starts the fake runner for the queue in $Q and waits for its heartbeat; the EXIT trap kills it.
start_runner() {
  if [ -n "$runner_pid" ]; then kill "$runner_pid" 2>/dev/null; wait "$runner_pid" 2>/dev/null; fi
  "$py" -I "$tmp/fake/runner.py" "$Q" >/dev/null 2>&1 &
  runner_pid=$!
  local i=0
  until [ -s "$tmp/run/queue-runner.json" ] || [ "$i" -gt 60 ]; do i=$((i + 1)); sleep 0.05; done
}

# Polling for a separately started fake-runner process to grant each job: integration group.
# Run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/slot-record.sh.
if [ "${CODETEAM_TEST_GROUP:-unit}" = integration ]; then
# 1. A gated build from a team-x worktree.
rm -rf "$tmp/run"; mkdir -p "$Q"; chmod 700 "$Q"
start_runner
(cd "$proj" && env -i PATH="$path" HOME="$HOME" GIT_CEILING_DIRECTORIES="$tmp" CODETEAM_QUEUE_DIR="$Q" CODETEAM_BUILDQ_LAUNCH="$here/zone/tests/fake-launchctl" \
  CODETEAM_BUILDQ_TICK=0.05 CODETEAM_SESSION=s1 \
  "$slot" cargo build >"$tmp/c1.out" 2>"$tmp/c1.err")
rc=$?
jf="$(job_file)"
pid_tool="$(sed -n 's/^pid=//p' "$tmp/c1.out")"
if [ "$rc" = 7 ] && [ -n "$jf" ] \
   && [ "$(job_field "$jf" kind)" = '"slot"' ] \
   && [ "$(job_field "$jf" class)" = '"dev"' ] \
   && [ "$(job_field "$jf" pid)" = "$pid_tool" ] \
   && [ "$(job_field "$jf" team)" = '"team-x"' ] \
   && [ "$(job_field "$jf" session)" = '"s1"' ] \
   && [ "$(job_field "$jf" worktree)" = "\"$proj\"" ] \
   && [ "$(job_field "$jf" tool)" = '"cargo"' ] \
   && [ "$(job_field "$jf" command)" = '["cargo", "build"]' ] \
   && [ "$(job_field "$jf" key)" = '"slot cargo"' ] \
   && [ "$(job_field "$jf" env)" = '{}' ] \
   && [ "$(grep -c '^pid=' "$tmp/c1.out")" = 1 ] \
   && [ "$(stat -f %Lp "$jf" 2>/dev/null)" = 600 ]; then
  ok "gated cargo build writes a slot job file and exits 7"
else
  bad "gated cargo build writes a slot job file and exits 7" "exit $rc, job [$jf], stdout [$(cat "$tmp/c1.out")], stderr [$(cat "$tmp/c1.err")]"
fi

# 2. CODETEAM_SESSION unset: session null.
rm -rf "$tmp/run"; mkdir -p "$Q"; chmod 700 "$Q"
start_runner
(cd "$proj" && env -i PATH="$path" HOME="$HOME" GIT_CEILING_DIRECTORIES="$tmp" CODETEAM_QUEUE_DIR="$Q" CODETEAM_BUILDQ_LAUNCH="$here/zone/tests/fake-launchctl" \
  CODETEAM_BUILDQ_TICK=0.05 "$slot" cargo build >"$tmp/c2.out" 2>"$tmp/c2.err")
rc=$?
jf="$(job_file)"
if [ "$rc" = 7 ] && [ -n "$jf" ] && [ "$(job_field "$jf" session)" = null ]; then
  ok "CODETEAM_SESSION unset: session is null"
else bad "CODETEAM_SESSION unset: session is null" "exit $rc, job [$jf], session $(job_field "$jf" session 2>/dev/null)"; fi

# 3. A folder outside any git repo: worktree and team null.
rm -rf "$tmp/run"; mkdir -p "$Q"; chmod 700 "$Q"
start_runner
(cd "$plain" && env -i PATH="$path" HOME="$HOME" GIT_CEILING_DIRECTORIES="$tmp" CODETEAM_QUEUE_DIR="$Q" CODETEAM_BUILDQ_LAUNCH="$here/zone/tests/fake-launchctl" \
  CODETEAM_BUILDQ_TICK=0.05 CODETEAM_SESSION=s1 "$slot" cargo build >"$tmp/c3.out" 2>"$tmp/c3.err")
rc=$?
jf="$(job_file)"
if [ "$rc" = 7 ] && [ -n "$jf" ] && [ "$(job_field "$jf" worktree)" = null ] && [ "$(job_field "$jf" team)" = null ]; then
  ok "cwd outside git: worktree and team null, exit 7"
else bad "cwd outside git: worktree and team null, exit 7" "exit $rc, job [$jf]"; fi

# 4. A git that fails, in a real repo: worktree and team null.
rm -rf "$tmp/run"; mkdir -p "$Q"; chmod 700 "$Q"
start_runner
(cd "$proj" && env -i PATH="$tmp/gitstub:$path" HOME="$HOME" GIT_CEILING_DIRECTORIES="$tmp" CODETEAM_QUEUE_DIR="$Q" CODETEAM_BUILDQ_LAUNCH="$here/zone/tests/fake-launchctl" \
  CODETEAM_BUILDQ_TICK=0.05 CODETEAM_SESSION=s1 "$slot" cargo build >"$tmp/c4.out" 2>"$tmp/c4.err")
rc=$?
jf="$(job_file)"
if [ "$rc" = 7 ] && [ -n "$jf" ] && [ "$(job_field "$jf" worktree)" = null ] && [ "$(job_field "$jf" team)" = null ]; then
  ok "failing git: worktree and team null, exit 7"
else bad "failing git: worktree and team null, exit 7" "exit $rc, job [$jf]"; fi

else
  echo "skip 1 gated cargo build writes a slot job file and exits 7: integration group only; run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/slot-record.sh"
  echo "skip 2 CODETEAM_SESSION unset: session is null: integration group only; run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/slot-record.sh"
  echo "skip 3 cwd outside git: worktree and team null, exit 7: integration group only; run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/slot-record.sh"
  echo "skip 4 failing git: worktree and team null, exit 7: integration group only; run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/slot-record.sh"
fi

# 5. Ungated cargo --version: no runner, no job file, exit 7.
if [ -n "$runner_pid" ]; then kill "$runner_pid" 2>/dev/null; wait "$runner_pid" 2>/dev/null; runner_pid=""; fi
rm -rf "$tmp/run"; mkdir -p "$Q"; chmod 700 "$Q"
(cd "$proj" && env -i PATH="$path" HOME="$HOME" GIT_CEILING_DIRECTORIES="$tmp" CODETEAM_QUEUE_DIR="$Q" CODETEAM_BUILDQ_LAUNCH="$here/zone/tests/fake-launchctl" \
  CODETEAM_BUILDQ=/nonexistent CODETEAM_BUILDQ_TICK=0.05 CODETEAM_SESSION=s1 "$slot" cargo --version >"$tmp/c5.out" 2>"$tmp/c5.err")
rc=$?
if [ "$rc" = 7 ] && [ -z "$(job_file)" ]; then ok "ungated cargo --version writes no job, exit 7"
else bad "ungated cargo --version writes no job, exit 7" "exit $rc, jobs [$(ls "$Q")]"; fi

# 6. CODETEAM_SLOT_HELD=1 on a gated build: no runner, no job file, the tool sees the flag.
rm -rf "$tmp/run"; mkdir -p "$Q"; chmod 700 "$Q"
(cd "$proj" && env -i PATH="$path" HOME="$HOME" GIT_CEILING_DIRECTORIES="$tmp" CODETEAM_QUEUE_DIR="$Q" CODETEAM_BUILDQ_LAUNCH="$here/zone/tests/fake-launchctl" \
  CODETEAM_BUILDQ=/nonexistent CODETEAM_BUILDQ_TICK=0.05 CODETEAM_SESSION=s1 CODETEAM_SLOT_HELD=1 "$slot" cargo build >"$tmp/c6.out" 2>"$tmp/c6.err")
rc=$?
if [ "$rc" = 7 ] && [ -z "$(job_file)" ] && grep -q '^held=1$' "$tmp/c6.out"; then
  ok "CODETEAM_SLOT_HELD=1 passes straight through: no job, exit 7"
else bad "CODETEAM_SLOT_HELD=1 passes straight through: no job, exit 7" "exit $rc, jobs [$(ls "$Q")], stdout [$(cat "$tmp/c6.out")]"; fi

# 7. CODETEAM_BUILDQ_TICKET=x on a gated build: no runner, no job file, the tool runs.
rm -rf "$tmp/run"; mkdir -p "$Q"; chmod 700 "$Q"
(cd "$proj" && env -i PATH="$path" HOME="$HOME" GIT_CEILING_DIRECTORIES="$tmp" CODETEAM_QUEUE_DIR="$Q" CODETEAM_BUILDQ_LAUNCH="$here/zone/tests/fake-launchctl" \
  CODETEAM_BUILDQ=/nonexistent CODETEAM_BUILDQ_TICK=0.05 CODETEAM_SESSION=s1 CODETEAM_BUILDQ_TICKET=x "$slot" cargo build >"$tmp/c7.out" 2>"$tmp/c7.err")
rc=$?
if [ "$rc" = 7 ] && [ -z "$(job_file)" ] && grep -q '^ticket=x$' "$tmp/c7.out"; then
  ok "CODETEAM_BUILDQ_TICKET set passes straight through: no job, exit 7"
else bad "CODETEAM_BUILDQ_TICKET set passes straight through: no job, exit 7" "exit $rc, jobs [$(ls "$Q")], stdout [$(cat "$tmp/c7.out")]"; fi

# slot_bare OUT ERR: a gated cargo build from the team-x worktree with no runner (CODETEAM_BUILDQ=/nonexistent), so the
# build falls back at once; the only thing it does to Q is create it, when Q is absent.
slot_bare() {
  (cd "$proj" && env -i PATH="$path" HOME="$HOME" GIT_CEILING_DIRECTORIES="$tmp" CODETEAM_QUEUE_DIR="$Q" CODETEAM_BUILDQ_LAUNCH="$here/zone/tests/fake-launchctl" \
    CODETEAM_BUILDQ=/nonexistent CODETEAM_BUILDQ_START_WAIT=0.3 CODETEAM_BUILDQ_TICK=0.05 CODETEAM_SESSION=s1 \
    "$slot" cargo build >"$1" 2>"$2")
}

# 8. Time Machine: the build creates Q, and makes no tmutil call.
if [ -n "$runner_pid" ]; then kill "$runner_pid" 2>/dev/null; wait "$runner_pid" 2>/dev/null; runner_pid=""; fi
rm -rf "$tmp/run" "$tmp/tm.log"
slot_bare "$tmp/c8.out" "$tmp/c8.err"; rc=$?
mode="$("$py" -I -c 'import os,sys; print(oct(os.stat(sys.argv[1]).st_mode & 0o777))' "$Q" 2>/dev/null)"
if [ "$rc" = 7 ] && [ "$mode" = 0o700 ] && [ ! -e "$tmp/tm.log" ]; then
  ok "a gated build that creates Q makes no tmutil call, exit 7, Q is 0700"
else bad "a gated build that creates Q makes no tmutil call, exit 7, Q is 0700" "exit $rc, Q mode [$mode], tm.log [$(cat "$tmp/tm.log" 2>/dev/null)], stderr [$(cat "$tmp/c8.err")]"; fi

# 9. Time Machine: Q exists already; the build makes no tmutil call.
rm -f "$tmp/tm.log"
slot_bare "$tmp/c9.out" "$tmp/c9.err"; rc=$?
if [ "$rc" = 7 ] && [ ! -e "$tmp/tm.log" ]; then
  ok "an existing Q gets no tmutil call, exit 7"
else bad "an existing Q gets no tmutil call, exit 7" "exit $rc, tm.log [$(cat "$tmp/tm.log" 2>/dev/null)]"; fi

exit $fail
