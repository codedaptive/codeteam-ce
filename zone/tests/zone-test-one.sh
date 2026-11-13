#!/bin/bash
# zone/tests/zone-test-one.sh: zone.mk's test-one fallback and zone-tool test-one, in a
# scratch repo with no Makefile, where zone.mk arrives only through MAKEFILES (as codeteam
# loads it), and in a scratch repo whose own Makefile defines test-one.
# The build queue stays out of it: CODETEAM_QUEUE_DIR is scratch and CODETEAM_BUILDQ is
# /nonexistent; fake-launchctl reports no service, so job submit writes its job file in scratch and runs
# the test here in-process. ZONE_JOB_WAIT=0 makes make wait for it. The checks below
# read the records and output, which are the same either way; zone-job.sh and zone-job-mk.sh test the queue.
# Time Machine guard (zone/docs/TESTING.md): a stub tmutil first on PATH, so no check reaches the real Time Machine. This file
# adds no check of the queue's own (the queue's checks are in zone-job.sh and zone-job-mk.sh).
#  1. DIR=pkg (pytest passes): exit 0, record "one pkg owns=" PASS (repo A has no makefile, so keys end in owns=).
#  2. DIR=shpkg (shpkg/tests/a.sh exits 0): record PASS.
#  3. DIR=bad (pytest fails): non-zero exit, record FAIL, output names test_bad.
#  4. DIR=badsh (badsh/tests/b.sh exits 1): record FAIL, output names b.sh.
#  5. DIR=docs (no tests) and DIR=nope (missing): exit 0, "no tests", docs record PASS.
#  6. make zone-test with CODETEAM_ZONE=. and CODETEAM_OWNS listing passing entries: PASS
#     (the ./rust leg finds no tests); with a failing entry: FAIL.
#  7. DIR=tests: tests/c.sh runs, tests/run.sh never runs.
#  8. A .py file and a .sh file as DIR: PASS.
#  9. make -C <repo> zone-test-one from another folder: PASS.
# 10. DIR=. with CODETEAM_OWNS empty: non-zero, output names CODETEAM_OWNS.
# 11. A repo with its own Makefile: its test-one runs, zone.mk's does not, and its record
#     key has no owns= ("one pkg").
# 12. DIR=. on unchanged code, CODETEAM_OWNS in the environment: pkg passes, then pkg:bad
#     runs again and fails naming test_bad, then empty is refused (not a replayed PASS).
# 13. DIR=./ is the repo root too: with CODETEAM_OWNS=pkg only pkg runs (no test_bad);
#     with it empty, refused.
# 14. make zone-test ZONE_TEST_FLAGS=--cached, CODETEAM_ZONE=. and CODETEAM_OWNS in the
#     environment, unchanged code: OWNS=pkg passes, pkg:bad runs again and fails naming
#     test_bad, empty is refused naming CODETEAM_OWNS (no replayed PASS); each run writes
#     .test-record.json (the suite record, not a keyed one) with salt "owns=<CODETEAM_OWNS>".
# 15. Repo C, plain scripts in tests/unit and tests/integration named by owns globs: in the
#     unit group tests/unit's run as python3 FILE and tests/integration's are skipped with a line
#     saying so; a failing one fails the run naming it; in the integration group tests/integration's run.
# The outer session's make, zone and queue variables are cleared first, and group variables are kept from
# children, so the live checkout's zone.mk (MAKEFILES), an outer DIR in MAKEFLAGS, a job's own queue variables
# (CODETEAM_BUILDQ_TICKET, CODETEAM_SLOT_HELD) and outer group keys cannot leak into the scratch runs.
# ZONE_MK may be set from outside to run these checks against another zone.mk.
# Over 5 s in the integration group: each nested make -> zone-tool -> pytest or bash
# chain starts Python and hashes the repo so each record check sees its own record;
# about 4 s of CPU in all, more wall time when the machine is loaded.
set -u
# Integration only under the checks run real nested
# make and zone-tool commands, with pytest or bash for tests; roughly 125 s in all at load 80.
# Run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/zone-test-one.sh
if [ "${CODETEAM_TEST_GROUP:-unit}" != integration ]; then
  echo "skip zone-test-one.sh: every check runs real nested make and zone-tool commands: integration group only; run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/zone-test-one.sh"
  exit 0
fi
unset MAKEFLAGS MFLAGS MAKELEVEL MAKEOVERRIDES DIR MAKEFILES CODETEAM_ZONE CODETEAM_OWNS \
      ZONE ZONE_ROOT ZONE_TOOL ZONE_TEST ZONE_TEST_FLAGS CODETEAM_BUILDQ_TICKET CODETEAM_SLOT_HELD
# Stage 2 (v5.2) sets GROUP and CODETEAM_TEST_GROUP: children must not inherit them or their record keys change.
# export -n keeps the outer values available to this script without exporting them.
export -n GROUP CODETEAM_TEST_GROUP
here="$(cd "$(dirname "$0")/../.." && pwd)"
ZONE_MK="${ZONE_MK:-$here/zone/zone.mk}"
export CODETEAM_HOME="$here"
# The scratch repos' .gitignore keeps __pycache__ out of the code hash;
# PYTHONDONTWRITEBYTECODE keeps bytecode from being written at all.
export PYTHONDONTWRITEBYTECODE=1
py=python3
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
# Time Machine guard (zone/docs/TESTING.md): a stub tmutil first on PATH, so no check reaches the real Time Machine.
mkdir -p "$tmp/stub"
cat > "$tmp/stub/tmutil" <<'SH'
#!/bin/sh
echo "$*" >> "$TMUTIL_LOG"
exit 0
SH
chmod +x "$tmp/stub/tmutil"
export PATH="$tmp/stub:$PATH" TMUTIL_LOG="$tmp/tmutil.log"
export CODETEAM_QUEUE_DIR="$tmp/run/queue" CODETEAM_BUILDQ=/nonexistent CODETEAM_BUILDQ_LAUNCH="$here/zone/tests/fake-launchctl" ZONE_JOB_WAIT=0 \
       CODETEAM_BUILDQ_TICK=0.05 CODETEAM_BUILDQ_IDLE_EXIT=1
export GIT_CEILING_DIRECTORIES="$tmp"
mk="$tmp/markers"; mkdir -p "$mk"   # markers live outside the repos: not part of the code hash
fail=0
ok()  { echo "ok   $1"; }
bad() { echo "FAIL $1: $2"; fail=1; }

newrepo() {  # $1 dir; files are written by the caller before commit()
  mkdir -p "$1"; git -C "$1" init -q
  printf '__pycache__/\n.pytest_cache/\n' > "$1/.gitignore"
}
commit() { git -C "$1" add -A && git -C "$1" -c user.email=t@t -c user.name=t commit -qm init; }

# The record's result for a key ("" = the zone suite's .test-record.json), or NONE.
record() {
  "$py" -I -c '
import json, pathlib, sys
root, key = pathlib.Path(sys.argv[1]), sys.argv[2]
if not key:
    p = root / ".test-record.json"
    print(json.loads(p.read_text()).get("result") if p.exists() else "NONE"); sys.exit()
for p in root.glob(".test-record-*.json"):
    r = json.loads(p.read_text())
    if (r.get("key") or "").strip() == key:
        print(r.get("result")); sys.exit()
print("NONE")' "$1" "$2"
}

# --- repo A: no Makefile ---------------------------------------------------------------
A="$tmp/a"; newrepo "$A"
mkdir -p "$A/pkg/tests" "$A/shpkg/tests" "$A/bad/tests" "$A/badsh/tests" "$A/docs" "$A/tests"
printf 'def test_ok():\n    assert True\n' > "$A/pkg/tests/test_ok.py"
printf '#!/bin/bash\nexit 0\n' > "$A/shpkg/tests/a.sh"
printf 'def test_bad():\n    assert False\n' > "$A/bad/tests/test_bad.py"
printf '#!/bin/bash\nexit 1\n' > "$A/badsh/tests/b.sh"
echo readme > "$A/docs/README"
echo readme > "$A/README"
printf '#!/bin/bash\ntouch %s/run-sh-ran\nexit 0\n' "$mk" > "$A/tests/run.sh"
printf '#!/bin/bash\ntouch %s/c-sh-ran\nexit 0\n' "$mk" > "$A/tests/c.sh"
chmod +x "$A"/*/tests/*.sh "$A"/tests/*.sh
commit "$A"

out=""; rc=0
zmake() {  # run make in repo A from its root with zone.mk only through MAKEFILES
  out="$(cd "$A" && MAKEFILES="$ZONE_MK" make --no-print-directory "$@" 2>&1)"; rc=$?
}
expect() {  # $1 label, $2 want exit (0|nz), $3 record key or - , $4 want record, $5 text the output must hold or ""
  local label=$1 wantrc=$2 key=$3 wantrec=$4 text=$5 why=""
  if [ "$wantrc" = 0 ] && [ "$rc" -ne 0 ]; then why="exit $rc, want 0"; fi
  if [ "$wantrc" = nz ] && [ "$rc" -eq 0 ]; then why="exit 0, want non-zero"; fi
  if [ -z "$why" ] && [ "$key" != - ]; then
    local got; got="$(record "$A" "$key")"
    [ "$got" = "$wantrec" ] || why="record [$key] is $got, want $wantrec"
  fi
  if [ -z "$why" ] && [ -n "$text" ] && ! grep -q -- "$text" <<<"$out"; then why="output lacks '$text'"; fi
  if [ -z "$why" ]; then ok "$label"; else bad "$label" "$why; output tail: $(tail -3 <<<"$out" | tr '\n' '|')"; fi
}

zmake zone-test-one DIR=pkg;    expect "1 DIR=pkg passing pytest: PASS record" 0 "one pkg owns=" PASS ""
zmake zone-test-one DIR=shpkg;  expect "2 DIR=shpkg passing shell test: PASS record" 0 "one shpkg owns=" PASS ""
zmake zone-test-one DIR=bad;    expect "3 DIR=bad failing pytest: FAIL record naming test_bad" nz "one bad owns=" FAIL test_bad
zmake zone-test-one DIR=badsh;  expect "4 DIR=badsh failing shell test: FAIL record naming b.sh" nz "one badsh owns=" FAIL b.sh
zmake zone-test-one DIR=docs;   expect "5 DIR=docs (no tests): PASS record, says no tests" 0 "one docs owns=" PASS "no tests"
zmake zone-test-one DIR=nope;   expect "5 DIR=nope (missing): exit 0, says no tests" 0 - - "no tests"

zmake zone-test CODETEAM_ZONE=. CODETEAM_OWNS=pkg:shpkg:docs:README
expect "6 zone-test, owned entries all pass: PASS record" 0 "" PASS ""
zmake zone-test CODETEAM_ZONE=. CODETEAM_OWNS=pkg:bad
expect "6 zone-test, an owned entry fails: FAIL record" nz "" FAIL ""

rm -f "$mk/run-sh-ran" "$mk/c-sh-ran"
zmake zone-test-one DIR=tests
if [ "$rc" -eq 0 ] && [ -e "$mk/c-sh-ran" ] && [ ! -e "$mk/run-sh-ran" ]; then ok "7 DIR=tests: c.sh ran, run.sh did not"
else bad "7 DIR=tests" "exit $rc, c.sh ran: $([ -e "$mk/c-sh-ran" ] && echo yes || echo no), run.sh ran: $([ -e "$mk/run-sh-ran" ] && echo yes || echo no); output tail: $(tail -3 <<<"$out" | tr '\n' '|')"; fi

zmake zone-test-one DIR=pkg/tests/test_ok.py; expect "8 DIR=<a .py file>: PASS" 0 "one pkg/tests/test_ok.py owns=" PASS ""
zmake zone-test-one DIR=shpkg/tests/a.sh;     expect "8 DIR=<a .sh file>: PASS" 0 "one shpkg/tests/a.sh owns=" PASS ""

# A fresh key (pkg/tests, never run above), so --cached cannot answer from an earlier record.
out="$(cd "$tmp" && MAKEFILES="$ZONE_MK" make --no-print-directory -C "$A" zone-test-one DIR=pkg/tests 2>&1)"; rc=$?
expect "9 make -C <repo> from another folder: PASS" 0 "one pkg/tests owns=" PASS ""

zmake zone-test-one DIR=. CODETEAM_OWNS=
expect "10 DIR=. with CODETEAM_OWNS empty: refused, names CODETEAM_OWNS" nz - - CODETEAM_OWNS

# 12 and 13 pass CODETEAM_OWNS in make's environment, as a lane session has it, not as a
# make command-line variable. The code is unchanged between runs, so a record keyed
# without CODETEAM_OWNS would replay the first answer for every later OWNS.
zmake_owns() {  # $1 CODETEAM_OWNS, rest: make arguments
  local owns=$1; shift
  out="$(cd "$A" && env CODETEAM_OWNS="$owns" MAKEFILES="$ZONE_MK" make --no-print-directory "$@" 2>&1)"; rc=$?
}
zmake_owns pkg zone-test-one DIR=.
expect "12 DIR=. CODETEAM_OWNS=pkg (env): exit 0" 0 - - ""
zmake_owns pkg:bad zone-test-one DIR=.
expect "12 DIR=. CODETEAM_OWNS=pkg:bad, unchanged code: runs again, fails naming test_bad" nz - - test_bad
zmake_owns "" zone-test-one DIR=.
expect "12 DIR=. CODETEAM_OWNS empty, unchanged code: refused, names CODETEAM_OWNS" nz - - CODETEAM_OWNS

zmake_owns pkg zone-test-one DIR=./
if [ "$rc" -eq 0 ] && ! grep -q test_bad <<<"$out"; then ok "13 DIR=./ CODETEAM_OWNS=pkg: owned paths only, bad's test did not run"
else bad "13 DIR=./ CODETEAM_OWNS=pkg" "exit $rc, test_bad in output: $(grep -q test_bad <<<"$out" && echo yes || echo no); output tail: $(tail -3 <<<"$out" | tr '\n' '|')"; fi
zmake_owns "" zone-test-one DIR=./
expect "13 DIR=./ CODETEAM_OWNS empty: refused, names CODETEAM_OWNS" nz - - CODETEAM_OWNS

# 14: the suite record (.test-record.json) on unchanged code, CODETEAM_OWNS in the
# environment. Its hash ignores CODETEAM_OWNS, so the record carries it as a salt, and a
# record with another salt must not answer --cached.
salt() {  # the suite record's salt, or NONE
  "$py" -I -c '
import json, pathlib, sys
p = pathlib.Path(sys.argv[1]) / ".test-record.json"
print(json.loads(p.read_text()).get("salt", "NONE") if p.exists() else "NONE")' "$A"
}
expect14() {  # $1 label, $2 want exit (0|nz), $3 want suite record, $4 output text, $5 want salt
  expect "$1" "$2" "" "$3" "$4"
  local got; got="$(salt)"
  [ "$got" = "$5" ] || bad "$1 (salt)" ".test-record.json salt is $got, want $5"
}
# Start from no suite record, so the first run writes a PASS that a later OWNS could replay.
rm -f "$A/.test-record.json"
zmake_owns pkg zone-test CODETEAM_ZONE=. ZONE_TEST_FLAGS=--cached
expect14 "14 zone-test --cached CODETEAM_OWNS=pkg (env): PASS in .test-record.json" 0 PASS "" "owns=pkg"
zmake_owns pkg:bad zone-test CODETEAM_ZONE=. ZONE_TEST_FLAGS=--cached
expect14 "14 zone-test --cached CODETEAM_OWNS=pkg:bad, unchanged code: runs again, fails naming test_bad" nz FAIL test_bad "owns=pkg:bad"
zmake_owns "" zone-test CODETEAM_ZONE=. ZONE_TEST_FLAGS=--cached
expect14 "14 zone-test --cached CODETEAM_OWNS empty, unchanged code: refused, names CODETEAM_OWNS" nz FAIL CODETEAM_OWNS "owns="

# --- repo C: no Makefile; plain scripts in tests/unit and tests/integration -------
# 15: Stage 2 runs a .py that is not a pytest file by name in tests/unit (unit step) and tests/integration
# (integration step) as `python3 <file>`; an owns list naming them by glob runs them the same way, each in its group.
C="$tmp/c"; newrepo "$C"
mkdir -p "$C/tests/unit" "$C/tests/integration"
printf 'open("%s/c-unit-ran", "w").close()\n' "$mk" > "$C/tests/unit/land-ok.py"
printf 'import sys\nsys.exit(1)\n' > "$C/tests/unit/land-bad.py"
printf 'open("%s/c-int-ran", "w").close()\n' "$mk" > "$C/tests/integration/land-int.py"
commit "$C"
zmake_c() {  # $1 CODETEAM_OWNS, $2 CODETEAM_TEST_GROUP, rest: make arguments
  local owns=$1 group=$2; shift 2
  out="$(cd "$C" && env CODETEAM_OWNS="$owns" CODETEAM_TEST_GROUP="$group" MAKEFILES="$ZONE_MK" make --no-print-directory "$@" 2>&1)"; rc=$?
}
rm -f "$mk/c-unit-ran" "$mk/c-int-ran"
zmake_c "tests/unit/land-ok.py:tests/integration/land-*.py" unit zone-test-one DIR=.
if [ "$rc" -eq 0 ] && [ -e "$mk/c-unit-ran" ] && [ ! -e "$mk/c-int-ran" ] && grep -q "skipped 1 script(s) in tests/integration" <<<"$out"
then ok "15 owned scripts, unit group: tests/unit's ran, tests/integration's skipped and said so"
else bad "15 owned scripts, unit group" "exit $rc, unit ran: $([ -e "$mk/c-unit-ran" ] && echo yes || echo no), integration ran: $([ -e "$mk/c-int-ran" ] && echo yes || echo no); output tail: $(tail -3 <<<"$out" | tr '\n' '|')"; fi
zmake_c "tests/unit/land-*.py" unit zone-test-one DIR=.
expect "15 an owned failing script: non-zero, names land-bad.py" nz - - land-bad.py
rm -f "$mk/c-int-ran"
zmake_c "tests/integration/land-*.py" integration zone-test-one DIR=.
if [ "$rc" -eq 0 ] && [ -e "$mk/c-int-ran" ]; then ok "15 owned scripts, integration group: tests/integration's ran"
else bad "15 owned scripts, integration group" "exit $rc, integration ran: $([ -e "$mk/c-int-ran" ] && echo yes || echo no); output tail: $(tail -3 <<<"$out" | tr '\n' '|')"; fi

# --- repo B: its own Makefile defines test-one -----------------------------------------
B="$tmp/b"; newrepo "$B"
mkdir -p "$B/pkg/tests"
printf 'def test_ok():\n    open("%s/b-pytest-ran", "w").close()\n' "$mk" > "$B/pkg/tests/test_ok.py"
printf 'test-one:\n\t@touch %s/b-own-test-one\n' "$mk" > "$B/Makefile"
commit "$B"
out="$(cd "$B" && MAKEFILES="$ZONE_MK" make --no-print-directory zone-test-one DIR=pkg 2>&1)"; rc=$?
brec="$(record "$B" "one pkg")"   # its key keeps the form without owns=
if [ "$rc" -eq 0 ] && [ -e "$mk/b-own-test-one" ] && [ ! -e "$mk/b-pytest-ran" ] && [ "$brec" = PASS ]; then ok "11 repo with its own Makefile: its test-one ran, zone.mk's did not, record keyed 'one pkg'"
else bad "11 own Makefile" "exit $rc, own test-one ran: $([ -e "$mk/b-own-test-one" ] && echo yes || echo no), pytest ran: $([ -e "$mk/b-pytest-ran" ] && echo yes || echo no), record [one pkg]: $brec; output tail: $(tail -3 <<<"$out" | tr '\n' '|')"; fi

exit $fail
