#!/bin/bash
# zone/tests/zone-tool-any-python.sh: guards that zone-tool still works when its shebang
# (`#!/usr/bin/env python3`) starts it on the system Python 3.9, as the push gate does under
# PATH=/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin (/usr/bin/python3 is 3.9 on this Mac).
# zone-tool re-runs itself under the first Python 3.11+ it finds, so test-one with
# CODETEAM_OWNS globs must run clean from that start. Red before the re-exec: cmd_test_one expands
# each owned entry with glob.glob(e, root_dir=root), which needs Python 3.10, so under 3.9 any
# owned entry died with a TypeError and a Traceback.
#  1. Info only, not a check: the python3 the shebang resolves to under that PATH, and its
#     version. It is printed, never failed or skipped, so a reader sees whether the checks below
#     ran on the old Python (3.9) or not (3.10+ is not a failure).
#  2. CODETEAM_OWNS=pkg:sh*: exit 0, no Traceback, pkg and shpkg tests ran ("ok   pkg",
#     "ok   shpkg/tests/a.sh"), and bad's test did not run (no test_bad in the output).
#  3. CODETEAM_OWNS=pkg:ba*: non-zero exit, no Traceback, the output names test_bad (the glob
#     entry matched bad).
#  4. CODETEAM_OWNS=pkg:nomatch*: exit 0, no Traceback (a glob that matches nothing is not an
#     error).
#  5. CODETEAM_OWNS=pkg/ (trailing slash): exit 0, no Traceback, pkg's test ran ("ok   pkg").
# Every zone-tool run is in a scratch repo under mktemp -d in $TMPDIR, removed on exit. Each run
# first checks that its git top is inside that scratch tree, so the real worktree and the live
# checkout are never a cwd for zone-tool.
# The outer session's git, make and zone variables are cleared first, and group variables are kept from children.
# ZONE_PYTHON is cleared too: zone-tool's pytest children run on its default, python3.
set -u
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_COMMON_DIR GIT_OBJECT_DIRECTORY \
      GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_NAMESPACE GIT_PREFIX GIT_CEILING_DIRECTORIES \
      GIT_CONFIG GIT_CONFIG_PARAMETERS GIT_CONFIG_COUNT GIT_CONFIG_GLOBAL GIT_CONFIG_SYSTEM
unset MAKEFLAGS MFLAGS MAKELEVEL MAKEOVERRIDES DIR MAKEFILES CODETEAM_ZONE CODETEAM_OWNS \
      ZONE ZONE_ROOT ZONE_TOOL ZONE_TEST ZONE_TEST_FLAGS ZONE_PYTHON
# Stage 2 (v5.2) sets GROUP and CODETEAM_TEST_GROUP: children must not inherit them or their record keys change.
# export -n keeps the outer values available to this script without exporting them.
export -n GROUP CODETEAM_TEST_GROUP
here="$(cd "$(dirname "$0")/../.." && pwd)"
tool="$here/bin/zone-tool"
export CODETEAM_HOME="$here"
export PYTHONDONTWRITEBYTECODE=1
P=/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin
tmp="$(mktemp -d)" || exit 2
tmp="$(cd "$tmp" && pwd -P)"   # the realpath: git reports realpaths, so the prefix checks compare them
trap 'rm -rf "$tmp"' EXIT
export GIT_CEILING_DIRECTORIES="$tmp"
export GIT_CONFIG_GLOBAL="$tmp/gitconfig"; : > "$GIT_CONFIG_GLOBAL"
export GIT_CONFIG_NOSYSTEM=1
pass=0; fail=0; why=""
ok()  { echo "ok   $1"; pass=$((pass+1)); }
bad() { echo "FAIL $1: $2"; fail=$((fail+1)); }
add_why() { why="${why:+$why; }$1"; }
finish() { if [ -z "$why" ]; then ok "$1"; else bad "$1" "$why"; fi; why=""; }

# --- the scratch repo: pkg (passing pytest), shpkg (passing shell test), bad (failing pytest) --
R="$tmp/repo"
mkdir -p "$R/pkg" "$R/shpkg/tests" "$R/bad" || { echo "setup failed: mkdir"; exit 2; }
printf '__pycache__/\n.pytest_cache/\n' > "$R/.gitignore"
printf 'def test_ok():\n    assert True\n' > "$R/pkg/test_ok.py"
printf '#!/bin/bash\nexit 0\n' > "$R/shpkg/tests/a.sh"
printf 'def test_bad():\n    assert False\n' > "$R/bad/test_bad.py"
git -C "$R" init -q || { echo "setup failed: git init"; exit 2; }
git -C "$R" add -A && git -C "$R" -c user.name=t -c user.email=t@t commit -qm init || { echo "setup failed: commit"; exit 2; }

# --- 1 (info, not a check) -----------------------------------------------------------------
pyinfo="$(env PATH="$P" python3 -c 'import sys; print(sys.executable, sys.version.split()[0])' 2>&1)" || pyinfo="(python3 not found: $pyinfo)"
case "$pyinfo" in
  *" 3.9."*) pyand="the old Python this test is for: zone-tool starts on it and must re-run itself under 3.11+" ;;
  *)         pyand="not 3.9, so the checks below may not start zone-tool on an old Python (not a failure, not a skip)" ;;
esac
echo "info: python3 under PATH=$P is $pyinfo: $pyand"

out=""; rc=0
zt() {  # $1 CODETEAM_OWNS: `zone-tool test-one .` run by its shebang under PATH=$P, from the scratch repo; sets rc and out
  local top; top="$(cd "$R" && git rev-parse --show-toplevel 2>/dev/null)"
  case "$top" in "$tmp"/*) ;; *) echo "refusing zone-tool: $R has top [$top], outside $tmp"; exit 3;; esac
  out="$(cd "$R" && env PATH="$P" CODETEAM_OWNS="$1" "$tool" test-one . 2>&1)"; rc=$?
}
has()  { grep -qF -- "$1" <<<"$out"; }
last() { tail -2 <<<"$out" | tr '\n' '|'; }

# --- 2 -----------------------------------------------------------------------------------
zt "pkg:sh*"
[ "$rc" -eq 0 ] || add_why "exit $rc, want 0: $(last)"
has Traceback && add_why "Traceback in the output: $(last)"
has "ok   pkg" || add_why "pkg's test did not run (no 'ok   pkg')"
has "ok   shpkg/tests/a.sh" || add_why "shpkg's test did not run (no 'ok   shpkg/tests/a.sh')"
has test_bad && add_why "bad's test ran (test_bad is in the output)"
finish "2 CODETEAM_OWNS=pkg:sh*: exit 0, no Traceback, pkg and shpkg run, bad does not"

# --- 3 -----------------------------------------------------------------------------------
zt "pkg:ba*"
[ "$rc" -ne 0 ] || add_why "exit 0, want non-zero"
has Traceback && add_why "Traceback in the output: $(last)"
has test_bad || add_why "output does not name test_bad: $(last)"
finish "3 CODETEAM_OWNS=pkg:ba*: non-zero exit, no Traceback, output names test_bad"

# --- 4 -----------------------------------------------------------------------------------
zt "pkg:nomatch*"
[ "$rc" -eq 0 ] || add_why "exit $rc, want 0: $(last)"
has Traceback && add_why "Traceback in the output: $(last)"
finish "4 CODETEAM_OWNS=pkg:nomatch*: exit 0, no Traceback (a glob that matches nothing is not an error)"

# --- 5 -----------------------------------------------------------------------------------
zt "pkg/"
[ "$rc" -eq 0 ] || add_why "exit $rc, want 0: $(last)"
has Traceback && add_why "Traceback in the output: $(last)"
has "ok   pkg" || add_why "pkg's test did not run (no 'ok   pkg')"
finish "5 CODETEAM_OWNS=pkg/ (trailing slash): exit 0, no Traceback, pkg's test runs"

echo "== zone-tool-any-python: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
