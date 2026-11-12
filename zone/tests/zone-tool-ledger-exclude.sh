#!/bin/bash
# zone/tests/zone-tool-ledger-exclude.sh: zone-tool's ledger writer (write_ledger, reached by
# every mutating `zone-tool ledger` op, close included) keeps .ledger.md and .ledger-closed out
# of git's view: it adds the lines /.ledger.md and /.ledger-closed to the common dir's
# info/exclude (git rev-parse --git-path info/exclude), which every linked worktree shares.
#  1. A linked worktree: `ledger add r1`, then `ledger close r1`: both files are written, and
#     `git add -A` stages neither.
#  2. The common info/exclude holds /.ledger.md and /.ledger-closed exactly once each after two
#     more ops (add r2, close r2).
#  3. A pre-existing info/exclude whose last line keep-me has no trailing newline: after
#     `ledger add r3`, keep-me is still its own whole line, the earlier lines are unchanged and
#     in order, and the two ledger lines are whole lines.
#  4. The main checkout of the same scratch repo: `ledger add m1`, then `git add -A` stages no
#     ledger file.
# Every zone-tool run is in a scratch repo under mktemp -d in $TMPDIR, removed on exit. Each run
# first checks that its git top is inside that scratch tree, so the real worktree and the live
# checkout (whose common dir this test must never touch) are never a cwd for zone-tool.
# The outer session's git and make variables are cleared first, and group variables are kept from children.
set -u
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_COMMON_DIR GIT_OBJECT_DIRECTORY \
      GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_NAMESPACE GIT_PREFIX GIT_CEILING_DIRECTORIES \
      GIT_CONFIG GIT_CONFIG_PARAMETERS GIT_CONFIG_COUNT GIT_CONFIG_GLOBAL GIT_CONFIG_SYSTEM
unset MAKEFLAGS MFLAGS MAKELEVEL MAKEOVERRIDES DIR MAKEFILES CODETEAM_ZONE CODETEAM_OWNS \
      ZONE ZONE_ROOT ZONE_TOOL ZONE_TEST ZONE_TEST_FLAGS
# Stage 2 (v5.2) sets GROUP and CODETEAM_TEST_GROUP: children must not inherit them or their record keys change.
# export -n keeps the outer values available to this script without exporting them.
export -n GROUP CODETEAM_TEST_GROUP
here="$(cd "$(dirname "$0")/../.." && pwd)"
tool="$here/bin/zone-tool"
export CODETEAM_HOME="$here"
export PYTHONDONTWRITEBYTECODE=1
py=python3
tmp="$(mktemp -d)" || exit 2
tmp="$(cd "$tmp" && pwd -P)"   # the realpath: git reports realpaths, so the prefix checks compare them
trap 'rm -rf "$tmp"' EXIT
export GIT_CEILING_DIRECTORIES="$tmp"
export GIT_CONFIG_GLOBAL="$tmp/gitconfig"; : > "$GIT_CONFIG_GLOBAL"
export GIT_CONFIG_NOSYSTEM=1
: > "$tmp/empty-ignore"
pass=0; fail=0; why=""
ok()  { echo "ok   $1"; pass=$((pass+1)); }
bad() { echo "FAIL $1: $2"; fail=$((fail+1)); }
add_why() { why="${why:+$why; }$1"; }
finish() { if [ -z "$why" ]; then ok "$1"; else bad "$1" "$why"; fi; why=""; }

A="$tmp/main"; W="$tmp/wt1"
setup() {  # the scratch main repo, one commit, and a linked worktree on branch wt1
  git init -q "$A" &&
  git -C "$A" config user.name t && git -C "$A" config user.email t@t &&
  git -C "$A" config core.excludesFile "$tmp/empty-ignore" &&
  echo readme > "$A/README" && git -C "$A" add -A && git -C "$A" commit -qm init &&
  git -C "$A" worktree add -q -b wt1 "$W"
}
setup || { echo "setup failed: scratch repo"; exit 2; }
common="$(git -C "$W" rev-parse --path-format=absolute --git-common-dir)" || { echo "setup failed: common dir"; exit 2; }
EXCL="$common/info/exclude"
case "$EXCL" in "$tmp"/*) ;; *) echo "setup failed: $EXCL is outside the scratch tree"; exit 2;; esac
mkdir -p "$common/info"

out=""; rc=0
zt() {  # $1 dir, rest: ledger arguments; sets rc and out. Refuses a dir whose git top is outside the scratch tree.
  local dir=$1; shift
  local top; top="$(cd "$dir" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null)"
  case "$top" in "$tmp"/*) ;; *) echo "refusing zone-tool: $dir has top [$top], outside $tmp"; exit 3;; esac
  out="$(cd "$dir" && "$py" "$tool" ledger "$@" 2>&1)"; rc=$?
}
ledger_staged() {  # $1 dir: prints the ledger files that `git add -A` stages there; status 2 if git failed
  local listing
  listing="$(git -C "$1" add -A && git -C "$1" diff --cached --name-only)" || return 2
  grep -xF -e .ledger.md -e .ledger-closed <<<"$listing"
  return 0
}
count_line() {  # $1 file, $2 line: how many lines of the file equal it exactly
  local n; n="$(grep -cxF -e "$2" "$1" 2>/dev/null)"; echo "${n:-0}"
}

# --- 1 -----------------------------------------------------------------------------------
zt "$W" add r1
[ "$rc" -eq 0 ] || add_why "ledger add r1 exit $rc: $out"
zt "$W" close r1
[ "$rc" -eq 0 ] || add_why "ledger close r1 exit $rc: $out"
for f in .ledger.md .ledger-closed; do
  [ -e "$W/$f" ] || add_why "$f not written in the linked worktree"
done
leaked="$(ledger_staged "$W")"; s=$?
if [ "$s" -ne 0 ]; then add_why "git add -A failed in the linked worktree"
elif [ -n "$leaked" ]; then add_why "git add -A stages $(tr '\n' ' ' <<<"$leaked")"; fi
finish "1 linked worktree: add r1 then close r1 write both files; git add -A stages neither"

# --- 2 -----------------------------------------------------------------------------------
zt "$W" add r2
[ "$rc" -eq 0 ] || add_why "ledger add r2 exit $rc: $out"
zt "$W" close r2
[ "$rc" -eq 0 ] || add_why "ledger close r2 exit $rc: $out"
for p in /.ledger.md /.ledger-closed; do
  n="$(count_line "$EXCL" "$p")"
  [ "$n" = 1 ] || add_why "$p is on $n lines of $EXCL, want exactly 1"
done
finish "2 common info/exclude holds /.ledger.md and /.ledger-closed exactly once each"

# --- 3 -----------------------------------------------------------------------------------
printf '# lead\n# mid\nkeep-me' > "$EXCL"   # no trailing newline on the last line
zt "$W" add r3
[ "$rc" -eq 0 ] || add_why "ledger add r3 exit $rc: $out"
[ "$(count_line "$EXCL" keep-me)" = 1 ] || add_why "keep-me is not its own whole line in $EXCL"
grep -vxF -e /.ledger.md -e /.ledger-closed "$EXCL" > "$tmp/c3.got"
printf '# lead\n# mid\nkeep-me\n' > "$tmp/c3.want"
cmp -s "$tmp/c3.got" "$tmp/c3.want" || add_why "lines other than the ledger lines are not '# lead', '# mid', 'keep-me' in order: $(tr '\n' '|' < "$tmp/c3.got")"
for p in /.ledger.md /.ledger-closed; do
  n="$(count_line "$EXCL" "$p")"
  [ "$n" = 1 ] || add_why "$p is on $n lines of $EXCL, want exactly 1"
done
finish "3 pre-existing exclude without trailing newline: keep-me whole, earlier lines unchanged and in order"

# --- 4 -----------------------------------------------------------------------------------
zt "$A" add m1
[ "$rc" -eq 0 ] || add_why "ledger add m1 exit $rc: $out"
[ -e "$A/.ledger.md" ] || add_why ".ledger.md not written in the main checkout"
leaked="$(ledger_staged "$A")"; s=$?
if [ "$s" -ne 0 ]; then add_why "git add -A failed in the main checkout"
elif [ -n "$leaked" ]; then add_why "git add -A stages $(tr '\n' ' ' <<<"$leaked")"; fi
finish "4 main checkout: add m1 writes .ledger.md; git add -A stages no ledger file"

echo "== zone-tool-ledger-exclude: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
