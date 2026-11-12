#!/bin/bash
# zone/tests/buildq-e2e.sh: the real runner, `zone-tool job` and codeteam-slot together, on a scratch git repo
# (zone/docs/SPEC.md and INTERFACE.md). The zone-tool and slot commands run under
# env -i with the stub PATH and scratch queue; fake-launchctl starts the scratch runner, never the live job.
#  1. (acceptance 1) budget 1: hold job 1 on a gate until `job wait --max 1` sees WAITING (4) with job 2 queued;
#     release the gate, then see DONE (0) with the record and output. Submission, running and completion allow 120 s each.
#  2. (acceptance 2) gate the job, find its ticket within 120 s, kill its waiting submitter, then release the gate
#     and wait up to 120 s for the job's PASS record.
#  3. (acceptance 7) after case 2 passes, `job submit --cached` repeats its command and matches the nonempty output
#     of `zone-tool test --cached`, exits 0 and leaves the queue entry count unchanged.
#  4. A gated `cargo build` through codeteam-slot outside a job writes a slot job file (kind slot, class dev), and the
#     tool runs with CODETEAM_SLOT_HELD=1 and exits 0.
#  5. The same build inside a job (a run job whose command calls codeteam-slot) passes straight through: no slot job
#     file is written, and the tool runs under the job's ticket.
#  6. sample a gate-held run job's env while running, release it, then compare its env once done.
# Cases 1-6 run only in the integration group; unit runs print six skips after setup.
# Run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/buildq-e2e.sh.
# Time Machine is never touched: a stub tmutil (first on PATH) records its argv and exits 0.
set -u
# Stage 2 (v5.2) sets GROUP and CODETEAM_TEST_GROUP: children must not inherit them or their record keys change.
# export -n keeps the outer values available to this script without exporting them.
export -n GROUP CODETEAM_TEST_GROUP
here="$(cd "$(dirname "$0")/../.." && pwd)"
zt="$here/bin/zone-tool"
slot="$here/bin/codeteam-slot"
runner="$here/bin/codeteam-buildq"
py=python3
tmp="$(cd "$(mktemp -d)" && pwd -P)"
repo="$tmp/repo"
path="$tmp/stub:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
fail=0
ok()  { echo "ok   $1"; }
bad() { echo "FAIL $1: $2"; fail=1; }

cleanup() {
  pkill -f "$tmp/" 2>/dev/null
  "$py" -I -c 'import json, os, signal, sys
try:
    os.kill(json.load(open(sys.argv[1]))["pid"], signal.SIGTERM)
except Exception:
    pass' "$tmp/run/queue-runner.json" 2>/dev/null
  rm -rf "$tmp"
}
trap cleanup EXIT

mkdir -p "$tmp/stub" "$tmp/slots" "$tmp/run/queue" "$repo"
printf 'budget = 1\n' > "$tmp/run/queue.toml"
printf '0.5\n0\n' > "$tmp/load"
# The stub tmutil (first on PATH) records its argv and exits 0; no run touches the real Time Machine settings.
cat > "$tmp/stub/tmutil" <<SH
#!/bin/sh
printf '%s\n' "\$*" >> "$tmp/tmutil.log"
exit 0
SH
chmod +x "$tmp/stub/tmutil"
# The stub cargo: records what ran, and the ticket it ran under.
cat > "$tmp/stub/cargo" <<SH
#!/bin/sh
echo "cargo ran held=\${CODETEAM_SLOT_HELD:-unset} ticket=\${CODETEAM_BUILDQ_TICKET:-unset}" >> "$tmp/cargo.mark"
SH
chmod +x "$tmp/stub/cargo"

# The environment every command here runs in: the stub PATH, the scratch queue, a 0.05 s tick and a
# one-second idle exit for the runner, and the scratch load file.
ENVLIST="PATH=$path HOME=$tmp CODETEAM_SESSION=s-e2e CODETEAM_QUEUE_DIR=$tmp/run/queue CODETEAM_BUILDQ_LAUNCH=$here/zone/tests/fake-launchctl CODETEAM_BUILDQ=$runner CODETEAM_BUILDQ_TICK=0.05 CODETEAM_BUILDQ_IDLE_EXIT=1 CODETEAM_BUILDQ_LOAD_FILE=$tmp/load CODETEAM_SLOT_DIR=$tmp/slots GIT_AUTHOR_NAME=frey GIT_AUTHOR_EMAIL=frey@example.invalid GIT_COMMITTER_NAME=frey GIT_COMMITTER_EMAIL=frey@example.invalid"
# ztool ARGS: zone-tool in the scratch repo. EXEC=exec makes it replace the calling subshell, so $! is its pid.
ztool() { ${EXEC:-} env -i $ENVLIST "$zt" "$@"; }
slotrun() { env -i $ENVLIST "$slot" "$@"; }
g() { env -i PATH="$path" HOME="$tmp" GIT_AUTHOR_NAME=frey GIT_AUTHOR_EMAIL=frey@example.invalid GIT_COMMITTER_NAME=frey GIT_COMMITTER_EMAIL=frey@example.invalid git -C "$repo" "$@"; }
# jobsum: one line per job file in the scratch queue: kind, class, ticket.
jobsum() {
  "$py" -I -c 'import glob, json, sys
for f in glob.glob(sys.argv[1] + "/*.json"):
    try:
        d = json.load(open(f))
    except ValueError:
        continue
    print(d.get("kind"), d.get("class"), d.get("ticket"))' "$tmp/run/queue"
}
# jf TICKET: prints the job file's state, then its env as JSON with sorted keys ("-" when the file has no env key).
jf() {
  "$py" -I -c 'import json, sys
d = json.load(open(sys.argv[1]))
print(d.get("state"), json.dumps(d["env"], sort_keys=True) if "env" in d else "-")' "$tmp/run/queue/$1.json" 2>/dev/null
}
# in_state TICKET STATE: the job file is in STATE.
in_state() { [ "$(jf "$1" | cut -d' ' -f1)" = "$2" ]; }
# has TEXT FIXED: TEXT contains the fixed string FIXED.
has() { printf '%s\n' "$1" | grep -qF "$2"; }
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
# findticket: sets t3 to the ticket of the job file whose key is e2e-two, once one exists.
findticket() {
  local f
  f="$(grep -lF 'e2e-two' "$tmp"/run/queue/*.json 2>/dev/null | head -1)"
  [ -n "$f" ] && t3="$(basename "$f" .json)"
  [ -n "${t3:-}" ]
}
# ticket_or_exited: the submitter has made its job file, or it has exited.
ticket_or_exited() { findticket || exited "$sub"; }

cd "$repo" || exit 1
g init -q
printf 'hello\n' > "$repo/a.txt"
g add a.txt
g commit -q -m init

# Real-runner waits (1, 2, 4, 5) and case 3's dependency on case 2's PASS record: integration group.
# Run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/buildq-e2e.sh.
if [ "${CODETEAM_TEST_GROUP:-unit}" = integration ]; then
# 1. Budget 1 holds job 2 queued behind gated job 1. Submission, running and WAITING then DONE each allow 120 s.
# These gated submits allow 120 s for runner startup under load. Submit job 1 in the background so fallback
# execution in the submitter cannot prevent the test from releasing its gate.
startwait="$ENVLIST CODETEAM_BUILDQ_START_WAIT=120"
( ENVLIST="$startwait" EXEC=exec ztool job submit --class dev --key e2e-one-a -- sh -c "while [ ! -e '$tmp/gate1' ]; do sleep 0.05; done; echo first" ) > "$tmp/e1.out" 2>&1 &
sub1=$!
if ! within 120 exited "$sub1"; then
  touch "$tmp/gate1"
  bad "1 job wait --max loop: WAITING (4) while queued, then DONE (0) with the record and output" "job 1's submit did not return within 120 s; the runner never came alive and the submitter is running the job itself"
else
  wait "$sub1"
  t1="$(cat "$tmp/e1.out")"
  if [ -z "$t1" ] || [ ! -f "$tmp/run/queue/$t1.json" ]; then
    bad "1 job wait --max loop: WAITING (4) while queued, then DONE (0) with the record and output" "job 1's submit returned no valid ticket with a job file (output [$t1])"
  elif ! within 120 in_state "$t1" running; then
    bad "1 job wait --max loop: WAITING (4) while queued, then DONE (0) with the record and output" "job 1 never reached running within 120 s (state [$(jf "$t1")])"
  else
    t2="$(ztool job submit --class dev --key e2e-one-b -- sh -c 'echo second')"
    codes=""
    out=""
    rc=""
    waited=no
    end=$(( $(date +%s) + 120 ))
    while [ "$(date +%s)" -lt "$end" ]; do
      out="$(ztool job wait "$t2" --max 1)"
      rc=$?
      codes="$codes $rc"
      [ "$rc" = 4 ] || break
      if [ "$waited" = no ]; then
        in_state "$t2" queued || break
        waited=yes
        touch "$tmp/gate1"
      fi
    done
    missing=""
    [ "$waited" = yes ] || missing="$missing no WAITING (4) with job 2 queued;"
    [ "$rc" = 0 ] || missing="$missing no DONE (0) within 120 s;"
    has "$out" "zone-test: PASS (exit 0); record " || missing="$missing no PASS record summary;"
    has "$out" second || missing="$missing no second in output;"
    if [ -z "$missing" ]; then
      ok "1 job wait --max loop: WAITING (4) while queued, then DONE (0) with the record and output"
    else
      bad "1 job wait --max loop: WAITING (4) while queued, then DONE (0) with the record and output" "$missing codes [$codes], last output [$out]"
    fi
  fi
fi
touch "$tmp/gate1"

# 2. Gate the job until its waiting submitter is killed. Allow 120 s each for the ticket and completion under load.
case2_cmd="while [ ! -e '$tmp/gate2' ]; do sleep 0.05; done; echo survived"
case2_ready=no
case2_ok=no
( ENVLIST="$startwait" EXEC=exec ztool job submit --class dev --key e2e-two --wait 0 -- sh -c "$case2_cmd" ) > "$tmp/e2.out" 2>&1 &
sub=$!
t3=""
if within 120 ticket_or_exited; then
  if findticket && ! exited "$sub"; then
    case2_ready=yes
  else
    bad "2 the job survives its submitter being killed: DONE with the PASS record and output" "submitter exited before it was killed (ticket [$t3], output [$(cat "$tmp/e2.out")])"
  fi
else
  bad "2 the job survives its submitter being killed: DONE with the PASS record and output" "no ticket within 120 s (output [$(cat "$tmp/e2.out")])"
fi
kill -9 "$sub" 2>/dev/null
wait "$sub" 2>/dev/null
touch "$tmp/gate2"
if [ "$case2_ready" = yes ]; then
  out="$(ztool job wait "$t3" --max 120)"
  rc=$?
  if [ "$rc" = 0 ] && has "$out" survived && has "$out" "zone-test: PASS (exit 0); record "; then
    ok "2 the job survives its submitter being killed: DONE with the PASS record and output"
    case2_ok=yes
  else
    bad "2 the job survives its submitter being killed: DONE with the PASS record and output" "ticket [$t3], exit $rc, output [$out]"
  fi
fi

# 3. Only after case 2 passes, repeat its command: compare cached output and the queue entry count.
if [ "$case2_ok" = yes ]; then
  n1="$(ls "$tmp/run/queue" | wc -l | tr -d ' ')"
  cached="$(ztool job submit --cached --key e2e-two -- sh -c "$case2_cmd")"
  crc=$?
  direct="$(ztool test --cached --key e2e-two -- sh -c "$case2_cmd")"
  n2="$(ls "$tmp/run/queue" | wc -l | tr -d ' ')"
  if [ "$crc" = 0 ] && [ -n "$cached" ] && [ "$cached" = "$direct" ] && [ "$n1" = "$n2" ]; then
    ok "3 a repeat on unchanged code is answered at submit time with no job file"
  else
    bad "3 a repeat on unchanged code is answered at submit time with no job file" "exit $crc, submit [$cached], test --cached [$direct], job files $n1 then $n2"
  fi
else
  bad "3 a repeat on unchanged code is answered at submit time with no job file" "not run: case 2 left no PASS record for e2e-two (see case 2)"
fi

# 4. A gated cargo build outside a job takes a slot job: the job file is kind slot, class dev, and the tool runs held.
slotrun cargo build
rc4=$?
if [ "$rc4" = 0 ] && grep -qF 'cargo ran held=1' "$tmp/cargo.mark" && jobsum | grep -q '^slot dev '; then
  ok "4 a gated cargo build outside a job gets a slot job (dev) and runs held"
else
  bad "4 a gated cargo build outside a job gets a slot job (dev) and runs held" "exit $rc4, slot jobs [$(jobsum | grep '^slot ')]"
fi

# 5. The same build inside a run job passes straight through: no new slot job, and it runs under the job's ticket.
s_before="$(jobsum | grep -c '^slot ')"
t5="$(ztool job submit --class dev --key e2e-nested -- sh -c "$slot cargo build")"
out5="$(ztool job wait "$t5" --max 120)"
rc5=$?
s_after="$(jobsum | grep -c '^slot ')"
if [ -n "$t5" ] && [ "$rc5" = 0 ] && [ "$s_before" = "$s_after" ] && grep -qF "ticket=$t5" "$tmp/cargo.mark"; then
  ok "5 a build inside a job passes straight through, under the job's ticket"
else
  bad "5 a build inside a job passes straight through, under the job's ticket" "job $t5, exit $rc5, output [$out5], slot jobs $s_before then $s_after"
fi
else
  echo "skip 1 job wait --max loop: WAITING (4) while queued, then DONE (0) with the record and output: integration group only; run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/buildq-e2e.sh"
  echo "skip 2 the job survives its submitter being killed: DONE with the PASS record and output: integration group only; run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/buildq-e2e.sh"
  echo "skip 3 a repeat on unchanged code is answered at submit time with no job file: integration group only; run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/buildq-e2e.sh"
  echo "skip 4 a gated cargo build outside a job gets a slot job (dev) and runs held: integration group only; run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/buildq-e2e.sh"
  echo "skip 5 a build inside a job passes straight through, under the job's ticket: integration group only; run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/buildq-e2e.sh"
fi

# 6. A gate holds the job running for the env sample; release it before waiting for done and comparing the env,
#    including the session zone-tool was given (ENVLIST sets CODETEAM_SESSION=s-e2e).
#    Allow up to 120 s each for the running state and completion, to accommodate heavy load.
#    This case is in the integration group because it cannot pass on a busy machine.
#    Run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/buildq-e2e.sh.
if [ "${CODETEAM_TEST_GROUP:-unit}" = integration ]; then
t6="$(ztool job submit --class dev --key e2e-six -- sh -c "while [ ! -e '$tmp/gate6' ]; do sleep 0.05; done; echo six")"
if ! within 120 in_state "$t6" running; then
  bad "6 a run job the real runner starts keeps its env while running and once done, the same env both times" "the job never reached running within 120 s (state [$(jf "$t6")])"
  touch "$tmp/gate6"
else
  running_jf="$(jf "$t6")"
  touch "$tmp/gate6"
  out6="$(ztool job wait "$t6" --max 120)"
  rc6=$?
  done_jf="$(jf "$t6")"
  renv="${running_jf#running }"
  denv="${done_jf#done }"
  if [ "${running_jf%% *}" = running ] && [ "${done_jf%% *}" = done ] && [ "$renv" != - ] && [ "$renv" = "$denv" ] \
    && has "$renv" '"CODETEAM_SESSION": "s-e2e"' && [ "$rc6" = 0 ]; then
    ok "6 a run job the real runner starts keeps its env while running and once done, the same env both times"
  else
    bad "6 a run job the real runner starts keeps its env while running and once done, the same env both times" "running [$running_jf], wait exit $rc6, done [$done_jf], output [$out6]"
  fi
fi
else
  echo "skip 6 a run job the real runner starts keeps its env while running and once done, the same env both times: integration group only; run with CODETEAM_TEST_GROUP=integration"
fi

exit $fail
