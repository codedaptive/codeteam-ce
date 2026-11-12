#!/bin/bash
# Check DIR scope, cache, root owns, argv, make fallback and the pre-test guard in a scratch repository.
set -u
unset MAKEFLAGS MFLAGS MAKELEVEL MAKEOVERRIDES DIR MAKEFILES ZONE_CHECK ZONE_CHECK_CMD CODETEAM_OWNS \
      CODETEAM_BUILDQ_TICKET CODETEAM_LANDING ZONE_WHOLE_BUDGET
# Stage 2 (v5.2) sets GROUP and CODETEAM_TEST_GROUP: children must not inherit them or their record keys change.
# export -n keeps the outer values available to this script without exporting them.
export -n GROUP CODETEAM_TEST_GROUP
HERE=$(cd "$(dirname "$0")/../.." && pwd)
W=$(mktemp -d)
trap 'rm -rf "$W"' EXIT
export GIT_CEILING_DIRECTORIES="$W" PYTHONDONTWRITEBYTECODE=1
R="$W/repo"
mkdir -p "$R/a" "$R/b" "$R/c"
git -C "$R" init -q || exit 1
printf 'x = 1\n' > "$R/a/ok.py"
printf 'def broken(:\n' > "$R/b/bad.py"
printf 'x = 2\n' > "$R/c/ok.py"
printf 'check:\n\t@printf "goals=$(MAKECMDGOALS) dir=$$DIR\\n" > "$$CHECK_LOG"\n' > "$R/Makefile"
git -C "$R" add -A && git -C "$R" -c user.email=t@t -c user.name=t commit -qm init || exit 1
cat > "$W/recorder" <<'SH'
#!/bin/sh
printf '%s\n' "$#" "$@" > "$CHECK_LOG"
SH
chmod +x "$W/recorder"
export CHECK_LOG="$W/check.log" ZONE_CHECK_CMD="$HERE/bin/py-syntax-check"
cd "$R" || exit 1
ok_count=0; bad_count=0
ok() { echo "ok   $1"; ok_count=$((ok_count + 1)); }
bad() { echo "FAIL $1: $2"; bad_count=$((bad_count + 1)); }
clear_guard() { rm -f "$R/.git/codeteam-test-guards.json"; }
check() { out=$("$HERE/bin/zone-tool" check "$1" 2>&1); rc=$?; }
expect_check() {
  local label=$1 want=$2 text=${3:-} last
  last=${out##*$'\n'}
  if [ "$rc" -eq "$want" ] && { { [ "$want" -eq 0 ] && [[ "$last" == 'zone-check: clean ('*')' ]]; } ||
      { [ "$want" -eq 1 ] && [[ "$last" == 'zone-check: FAILS ('*')' ]]; }; } &&
      { [ -z "$text" ] || [[ "$out" == *"$text"* ]]; }; then
    ok "$label"
  else
    bad "$label" "exit=$rc, last=$last, wanted exit=$want ${text:+and $text}"
  fi
}

clear_guard
check a; expect_check '1 check a ignores syntax error outside DIR' 0
clear_guard
check b; expect_check '2 check b reports its syntax error' 1 b/bad.py

clear_guard
check a; expect_check '3 cache: a initially clean' 0
check b; expect_check '3 cache: b fails after a' 1 b/bad.py
check a; expect_check '3 cache: a remains clean after b' 0

clear_guard
export CODETEAM_OWNS=a:c
check .; expect_check '4 root . checks owned a:c' 0
check ./; expect_check '4 root ./ checks owned a:c' 0
export CODETEAM_OWNS=a:b
check .; expect_check '4 root owns change includes bad b' 1 b/bad.py
export CODETEAM_OWNS=
check .; expect_check '4 root empty owns checks whole repo' 1 b/bad.py

clear_guard
export ZONE_CHECK_CMD="$W/recorder" CODETEAM_OWNS=
rm -f "$CHECK_LOG"
check a
if [ "$rc" -eq 0 ] && [ -f "$CHECK_LOG" ] && [ "$(cat "$CHECK_LOG")" = $'1\na' ]; then ok '5 argv: a is one argument'
else bad '5 argv: a is one argument' "exit=$rc, log=$(cat "$CHECK_LOG" 2>/dev/null)"; fi
clear_guard
rm -f "$CHECK_LOG"
export CODETEAM_OWNS=a:c
check .
if [ "$rc" -eq 0 ] && [ -f "$CHECK_LOG" ] && [ "$(cat "$CHECK_LOG")" = $'2\na\nc' ]; then ok '5 argv: root owned paths are separate arguments'
else bad '5 argv: root owned paths are separate arguments' "exit=$rc, log=$(cat "$CHECK_LOG" 2>/dev/null)"; fi
clear_guard
rm -f "$CHECK_LOG"
export CODETEAM_OWNS='[ca]'
check .
if [ "$rc" -eq 0 ] && [ -f "$CHECK_LOG" ] && [ "$(cat "$CHECK_LOG")" = $'2\na\nc' ]; then ok '5 argv: root glob expands in sorted order'
else bad '5 argv: root glob expands in sorted order' "exit=$rc, log=$(cat "$CHECK_LOG" 2>/dev/null)"; fi
clear_guard
rm -f "$CHECK_LOG"
export CODETEAM_OWNS=
check .
if [ "$rc" -eq 0 ] && [ -f "$CHECK_LOG" ] && [ "$(cat "$CHECK_LOG")" = 0 ]; then ok '5 argv: empty owns passes no arguments'
else bad '5 argv: empty owns passes no arguments' "exit=$rc, log=$(cat "$CHECK_LOG" 2>/dev/null)"; fi
clear_guard
rm -f "$CHECK_LOG"
export CODETEAM_OWNS=nosuch
check .
if [ "$rc" -eq 0 ] && [ ! -e "$CHECK_LOG" ]; then ok '5 argv: unmatched owns skips command'
else bad '5 argv: unmatched owns skips command' "exit=$rc, recorder ran=$([ -e "$CHECK_LOG" ] && echo yes || echo no)"; fi

clear_guard
rm -f "$CHECK_LOG"
unset ZONE_CHECK_CMD CODETEAM_OWNS
check a
if [ "$rc" -eq 0 ] && [ -f "$CHECK_LOG" ] && [ "$(cat "$CHECK_LOG")" = 'goals=check dir=a' ]; then ok '6 make fallback keeps check goal and DIR environment'
else bad '6 make fallback keeps check goal and DIR environment' "exit=$rc, log=$(cat "$CHECK_LOG" 2>/dev/null)"; fi

clear_guard
export ZONE_CHECK_CMD="$HERE/bin/py-syntax-check"
guard_out=$(python3 - "$HERE/bin/zone-tool" "$R" <<'PY'
import importlib.machinery, importlib.util, os, sys
from pathlib import Path
loader = importlib.machinery.SourceFileLoader('zt', sys.argv[1])
spec = importlib.util.spec_from_loader('zt', loader)
zt = importlib.util.module_from_spec(spec)
loader.exec_module(zt)
root = Path(sys.argv[2])
os.chdir(root)
h = zt.code_hash(root, None, zt.snapshot(root))
a = zt.guard_run(root, 'one a', h, False)
b = zt.guard_run(root, 'one b', h, False)
print('guard-a=' + ('PASS' if a is None else 'FAIL'))
print('guard-b=' + ('PASS' if b and 'REFUSED' in b and 'b/bad.py' in b else 'FAIL'))
PY
)
if grep -Fxq 'guard-a=PASS' <<< "$guard_out"; then ok '7 guard: one a allowed'; else bad '7 guard: one a allowed' "$(tr '\n' '|' <<< "$guard_out")"; fi
if grep -Fxq 'guard-b=PASS' <<< "$guard_out"; then ok '7 guard: one b refused with syntax error'; else bad '7 guard: one b refused with syntax error' "$(tr '\n' '|' <<< "$guard_out")"; fi

echo "$ok_count passed, $bad_count failed"
[ "$bad_count" -eq 0 ]
