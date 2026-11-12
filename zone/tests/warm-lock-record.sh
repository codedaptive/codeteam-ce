#!/bin/bash
# zone/tests/warm-lock-record.sh: share/claude-hooks/worktree-create.py writes the holder record into
# <git dir of the new worktree>/codeteam-warm.lock once its detached warm has started.
# 1. A warm in a team-* lane writes one JSON line: tool "warm", the worktree the hook printed, team "team-x",
#    session "s1" from CODETEAM_SESSION, since in epoch seconds, and pid = the warm wrapper's (the parent of
#    its make, alive while the warm runs).
# 2. CODETEAM_SESSION unset, or empty: session null.
# 3. A failed write (os.ftruncate and os.pwrite raise OSError) is swallowed: the hook exits 0, prints the
#    worktree, and the warm still runs to "warm ended: 0".
# Checks 1-3: integration group only (CODETEAM_TEST_GROUP=integration), skipped otherwise.
# 4. CODETEAM_WARM unset: no warm and no record; the hook exits 0 and prints the worktree.
# 5. Scratch-repo snapshot comparisons report run-named additions, not unrelated additions.
# slow: integration checks' detached warms wait for release and their logs; each wait has a 120-second bound.
# The scratch lane's stub `warm` writes its make's parent pid immediately, then holds for a release file.
# Holding on the event, rather than sleeping, keeps it alive during the pid checks under load; nothing builds.
# Session, Git and Python settings are cleared and HOME and Git config are isolated. Live-repo checks
# detect only per-run names: other lanes cut trees concurrently; printed worktree paths are checked under scratch.
set -u
# Stage 2 (v5.2) sets GROUP and CODETEAM_TEST_GROUP: children must not inherit them or their record keys change.
# export -n keeps the outer values available to this script without exporting them.
export -n GROUP CODETEAM_TEST_GROUP
# Preserve the test group before isolation clears every CODETEAM_* variable.
group="${CODETEAM_TEST_GROUP:-unit}"
for v in $(compgen -e); do
  case "$v" in CODETEAM_*|CT_*|GIT_*) unset "$v";; esac
done
unset PYTHONPATH PYTHONHOME
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null
here="$(cd "$(dirname "$0")/../.." && pwd)"
hook="$here/share/claude-hooks/worktree-create.py"
tmp="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$tmp"' EXIT
unset MAKEFILES MAKEFLAGS CODETEAM_ZONE CODETEAM_SWIFT_XCODE
export HOME="$tmp/home" XDG_CONFIG_HOME="$tmp/home/.config" PROBE="$tmp/probe"
export GIT_AUTHOR_NAME=frey GIT_AUTHOR_EMAIL=frey@example.invalid
export GIT_COMMITTER_NAME=frey GIT_COMMITTER_EMAIL=frey@example.invalid
fail=0
failed_checks=()
id="wlr$$"
# Delay the seed-index call after warm launch to reproduce a late hook return; 0 disables the delay.
WARM_LOCK_HOOK_DELAY="${WARM_LOCK_HOOK_DELAY:-0}"
export WARM_LOCK_HOOK_DELAY

# field FILE KEY: the record's value for KEY as JSON; <missing> or <unreadable> when there is none.
field() {
  python3 -I -c 'import json, sys
print(json.dumps(json.load(open(sys.argv[1])).get(sys.argv[2], "<missing>")))' "$1" "$2" 2>/dev/null || echo "<unreadable>"
}

# record_keys FILE: the record's keys, sorted, as JSON.
record_keys() {
  python3 -I -c 'import json, sys
print(json.dumps(sorted(json.load(open(sys.argv[1])))))' "$1" 2>/dev/null || echo "<unreadable>"
}

# lines_of FILE: the number of newlines in FILE (empty when FILE is absent).
lines_of() { { wc -l < "$1"; } 2>/dev/null | tr -d ' '; }

# gitdir_of WORKTREE: the worktree's absolute git dir (empty when the folder is not there).
gitdir_of() { [ -d "$1" ] && git -C "$1" rev-parse --path-format=absolute --git-dir; }

# warm_end LOG: wait at most 120 s; report ended/timed out and preserve the exit-status line for the check.
warm_end() {
  local deadline=$((SECONDS + 120))
  until grep -q '^warm ended' "$1" 2>/dev/null; do
    if [ "$SECONDS" -ge "$deadline" ]; then
      echo "timed out waiting for warm ended: $1"
      return 1
    fi
    sleep 0.1
  done
  echo "warm_end: ended ($1)" >&2
  tail -n 1 "$1" 2>/dev/null
}

# expect LABEL GOT WANT: one ok or FAIL line; retain failures for the stderr summary.
expect() {
  if [ "$2" = "$3" ]; then echo "ok   $1"
  else
    echo "FAIL $1: got [$2], want [$3]"
    failed_checks+=("$1: got [$2], want [$3]")
    fail=1
  fi
}

# call_hook NAME OUTPUT_NUMBER ENV_ARGS...: never invoke the hook with a manifest.
call_hook() {
  local name="$1" number="$2"
  shift 2
  if [ "${CODETEAM_MANIFEST+x}" = x ]; then
    echo "FAIL isolation: CODETEAM_MANIFEST is set"
    exit 1
  fi
  printf '{"name":"%s","cwd":"%s"}' "$name" "$lane" |
    env "$@" "$hook" > "$tmp/out$number" 2> "$tmp/err$number"
}

# Check Git reads independently so a failed read cannot produce an empty snapshot.
snapshot_repo() {
  local repo="$1" prefix="$2" refs worktrees status=0
  rm -f "$prefix-ref" "$prefix-worktree"
  if refs="$(git -C "$repo" for-each-ref --format='%(refname)')"; then
    printf '%s' "$refs" | LC_ALL=C sort > "$prefix-ref"
  else
    status=1
  fi
  if worktrees="$(git -C "$repo" worktree list --porcelain)"; then
    printf '%s' "$worktrees" | awk '/^worktree / {sub(/^worktree /, ""); print}' | LC_ALL=C sort > "$prefix-worktree"
  else
    status=1
  fi
  return "$status"
}

# Print additions whose refname contains $id, or whose worktree's last path component contains $id.
run_additions() {
  local line name
  while IFS= read -r line; do
    name="$line"
    [ "$1" = worktree ] && name="${line##*/}"
    case "$name" in *"$id"*) printf '%s\n' "$line" ;; esac
  done < <(LC_ALL=C comm -13 "$2" "$3")
  return 0
}

# Read-only toward the real repo: check only names for this run, because other lanes cut trees there
# concurrently. A worktree matches by its last path component, not by its parent folders.
# Missing snapshot files fail separately so a failed Git read cannot look like an empty snapshot.
live_snapshot() {
  local stage="$1" prefix="$tmp/live-$1"
  # The live repo is this checkout; a copy that is not a git checkout has nothing to compare.
  if ! git -C "$here" rev-parse --git-dir >/dev/null 2>&1; then
    echo "skip $stage: live repo: $here is not a git checkout"; return 0
  fi
  snapshot_repo "$here" "$prefix" || true
  if [ -f "$prefix-ref" ]; then
    expect "$stage: live repo: git for-each-ref succeeds" succeeded succeeded
    expect "$stage: live repo: no ref named for this run" "$(run_additions ref /dev/null "$prefix-ref")" ""
  else
    expect "$stage: live repo: git for-each-ref succeeds" failed succeeded
  fi
  if [ -f "$prefix-worktree" ]; then
    expect "$stage: live repo: git worktree list succeeds" succeeded succeeded
    expect "$stage: live repo: no worktree named for this run" "$(run_additions worktree /dev/null "$prefix-worktree")" ""
  else
    expect "$stage: live repo: git worktree list succeeds" failed succeeded
  fi
}

under_tmp() {
  case "$2" in "$tmp"/*) expect "$1: worktree is under the scratch folder" yes yes ;;
    *) expect "$1: worktree is under the scratch folder" no yes ;;
  esac
}

lane="$HOME/codeteam-work/team-x/workcrews/zone/lane"
mkdir -p "$PROBE" "$lane"
cat > "$lane/Makefile" <<'MAKE'
SHELL := /bin/bash
warm:
	@ps -o ppid= -p $$PPID | tr -d " " > "$$PROBE/$(notdir $(CURDIR))"
	@deadline=$$((SECONDS + 120)); \
	while [ ! -e "$$PROBE/$(notdir $(CURDIR)).release" ]; do \
	  if [ "$$SECONDS" -ge "$$deadline" ]; then \
	    echo timeout > "$$PROBE/$(notdir $(CURDIR)).wait"; exit 1; \
	  fi; \
	  sleep 0.1; \
	done; \
	echo released > "$$PROBE/$(notdir $(CURDIR)).wait"
MAKE
git -C "$lane" init -q && git -C "$lane" add Makefile && git -C "$lane" commit -q -m scratch \
  || { echo "FAIL setup: scratch lane repo"; exit 1; }

live_snapshot before
# checks 1-3 use a detached warm process and event waits with
# 120 s bounds (~61 s at load 80), so they belong to the integration group.
# Run: CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/warm-lock-record.sh
if [ "$group" = integration ]; then
  mkdir -p "$tmp/delay"
  cat > "$tmp/delay/sitecustomize.py" <<'PY'
import os
import subprocess
import time

original_run = subprocess.run

def delayed_run(args, *pos, **kwargs):
    if isinstance(args, (list, tuple)) and args and os.fspath(args[0]).endswith("codeteam-seed-index"):
        time.sleep(float(os.environ["WARM_LOCK_HOOK_DELAY"]))
    return original_run(args, *pos, **kwargs)

subprocess.run = delayed_run
PY
  t0="$(date +%s)"
  call_hook "$id-w1" 1 PYTHONPATH="$tmp/delay" CODETEAM_WARM=1 CODETEAM_SESSION=s1; rc1=$?
  t1="$(date +%s)"
  dest1="$(cat "$tmp/out1")"
  lock1="$(gitdir_of "$dest1")/codeteam-warm.lock"
  log1="$(dirname "$dest1")/warm-$id-w1.log"
  deadline=$((SECONDS + 120))
  until [ -s "$PROBE/$id-w1" ] || [ "$SECONDS" -ge "$deadline" ]; do sleep 0.1; done
  expect "check 1: warm probe arrived within 120 s" "$([ -s "$PROBE/$id-w1" ] && echo yes || echo 'timed out')" yes
  pid1="$(field "$lock1" pid)"
  alive1="$(kill -0 "$pid1" 2>/dev/null && echo yes)"

  # Check 1: the record of the warm the hook started.
  expect "check 1: hook exits 0" "$rc1" 0
  expect "check 1: hook prints the worktree" "$([ -d "$dest1" ] && echo yes)" yes
  under_tmp "check 1" "$dest1"
  expect "check 1: the record is one JSON line" "$(lines_of "$lock1")" 1
  expect "check 1: record keys" "$(record_keys "$lock1")" '["pid", "session", "since", "team", "tool", "worktree"]'
  expect "check 1: tool is warm" "$(field "$lock1" tool)" '"warm"'
  expect "check 1: worktree is the path the hook printed" "$(field "$lock1" worktree)" "\"$dest1\""
  expect "check 1: team is the team-* folder" "$(field "$lock1" team)" '"team-x"'
  expect "check 1: session is CODETEAM_SESSION" "$(field "$lock1" session)" '"s1"'
  expect "check 1: pid is alive while the warm runs" "$alive1" yes
  since1="$(field "$lock1" since)"
  case "$since1" in
    ''|*[!0-9]*) since_ok=no ;;
    *) [ "$since1" -ge "$((t0 - 1))" ] && [ "$since1" -le "$((t1 + 1))" ] && since_ok=yes || since_ok=no ;;
  esac
  expect "check 1: since is epoch seconds within the hook call" "$since_ok" yes
  expect "check 1: pid is the warm wrapper, the parent of its make" "$pid1" "$(cat "$PROBE/$id-w1" 2>/dev/null)"
  touch "$PROBE/$id-w1.release"
  expect "check 1: warm ended 0" "$(warm_end "$log1")" "warm ended: 0"
  expect "check 1: held warm was released" "$(cat "$PROBE/$id-w1.wait" 2>/dev/null)" released

  call_hook "$id-w2" 2 -u CODETEAM_SESSION CODETEAM_WARM=1; rc2=$?
  touch "$PROBE/$id-w2.release"
  call_hook "$id-w3" 3 CODETEAM_SESSION= CODETEAM_WARM=1; rc3=$?
  touch "$PROBE/$id-w3.release"

  mkdir -p "$tmp/sc"
  # Refuses every record write and says so on stderr, which shows the write was attempted and the stub loaded.
  printf '%s\n' 'import os, sys' 'def refuse(*args, **kwargs):' \
    '    sys.stderr.write("warm-lock test: write refused\n")' '    raise OSError(30, "read-only (test)")' \
    'os.ftruncate = refuse' 'os.pwrite = refuse' > "$tmp/sc/sitecustomize.py"
  call_hook "$id-w4" 4 PYTHONPATH="$tmp/sc" CODETEAM_WARM=1 CODETEAM_SESSION=s1; rc4=$?
  touch "$PROBE/$id-w4.release"

  # Check 2: session is null when CODETEAM_SESSION is unset or empty.
  dest2="$(cat "$tmp/out2")"
  lock2="$(gitdir_of "$dest2")/codeteam-warm.lock"
  expect "check 2: hook exits 0 without CODETEAM_SESSION" "$rc2" 0
  under_tmp "check 2" "$dest2"
  expect "check 2: session null when CODETEAM_SESSION is unset" "$(field "$lock2" session)" null
  dest3="$(cat "$tmp/out3")"
  expect "check 2: hook exits 0 with empty CODETEAM_SESSION" "$rc3" 0
  under_tmp "check 2" "$dest3"
  lock3="$(gitdir_of "$dest3")/codeteam-warm.lock"
  expect "check 2: session null when CODETEAM_SESSION is empty" "$(field "$lock3" session)" null
  expect "check 2: warm w2 ended 0" "$(warm_end "$(dirname "$dest2")/warm-$id-w2.log")" "warm ended: 0"
  expect "check 2: warm w3 ended 0" "$(warm_end "$(dirname "$dest3")/warm-$id-w3.log")" "warm ended: 0"

  # Check 3: a failed record write is swallowed; the hook and the warm go on.
  expect "check 3: hook exits 0 when the record write fails" "$rc4" 0
  dest4="$(cat "$tmp/out4")"
  expect "check 3: hook still prints the worktree" "$([ -d "$dest4" ] && echo yes)" yes
  under_tmp "check 3" "$dest4"
  expect "check 3: the refused write was attempted (stub marker on the hook's stderr)" "$(grep -q 'write refused' "$tmp/err4" && echo yes)" yes
  lock4="$(gitdir_of "$dest4")/codeteam-warm.lock"
  expect "check 3: the lock holds no valid record (empty or not JSON)" "$(field "$lock4" tool)" "<unreadable>"
  expect "check 3: warm still runs to ended 0" "$(warm_end "$(dirname "$dest4")/warm-$id-w4.log")" "warm ended: 0"
else
  echo "skip check 1 the warm hook's lock record: integration group only; run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/warm-lock-record.sh"
  echo "skip check 2 session null when CODETEAM_SESSION is unset or empty: integration group only; run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/warm-lock-record.sh"
  echo "skip check 3 a failed record write is swallowed: integration group only; run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/warm-lock-record.sh"
fi

call_hook "$id-w5" 5 -u CODETEAM_WARM CODETEAM_SESSION=s1; rc5=$?
live_snapshot after
for kind in ref worktree; do
  if [ -f "$tmp/live-before-$kind" ] && [ -f "$tmp/live-after-$kind" ]; then
    while IFS= read -r added; do
      expect "live repo: $kind named for this run added during the run: $added" added absent
    done < <(run_additions "$kind" "$tmp/live-before-$kind" "$tmp/live-after-$kind")
  fi
done

# Check 4: without CODETEAM_WARM there is no warm and no record.
expect "check 4: hook exits 0 without CODETEAM_WARM" "$rc5" 0
dest5="$(cat "$tmp/out5")"
expect "check 4: hook prints the worktree" "$([ -d "$dest5" ] && echo yes)" yes
under_tmp "check 4" "$dest5"
expect "check 4: no lock record" "$([ -s "$(gitdir_of "$dest5")/codeteam-warm.lock" ] && echo written || echo none)" none
expect "check 4: no warm log" "$([ -e "$(dirname "$dest5")/warm-$id-w5.log" ] && echo started || echo none)" none

# Check 5: compare scratch snapshots with run-named and unrelated additions to test the filter.
mkdir -p "$tmp/fake-repo" "$tmp/fake-wt"
git -C "$tmp/fake-repo" init -q && git -C "$tmp/fake-repo" commit -q --allow-empty -m scratch \
  || { echo "FAIL setup: fake repo"; exit 1; }
snapshot_repo "$tmp/fake-repo" "$tmp/fake-before"; fake_before_rc=$?
expect "check 5: before snapshot succeeds" "$fake_before_rc" 0
git -C "$tmp/fake-repo" worktree add -q -b wo/cli/agent-unrelated "$tmp/fake-wt/agent-unrelated" && \
  git -C "$tmp/fake-repo" worktree add -q -b "wo/zone/$id-leak" "$tmp/fake-wt/$id-leak" \
  || { echo "FAIL setup: fake worktrees"; exit 1; }
snapshot_repo "$tmp/fake-repo" "$tmp/fake-after"; fake_after_rc=$?
expect "check 5: after snapshot succeeds" "$fake_after_rc" 0
expect "check 5: an unrelated added ref is ignored, the run's is reported" \
  "$(run_additions ref "$tmp/fake-before-ref" "$tmp/fake-after-ref")" "refs/heads/wo/zone/$id-leak"
expect "check 5: an unrelated added worktree is ignored, the run's is reported" \
  "$(run_additions worktree "$tmp/fake-before-worktree" "$tmp/fake-after-worktree")" "$tmp/fake-wt/$id-leak"

if [ "$fail" -ne 0 ]; then
  printf 'warm-lock-record: FAIL: %s\n' "${failed_checks[@]}" >&2
else
  echo 'warm-lock-record: all checks ok' >&2
fi
exit "$fail"
