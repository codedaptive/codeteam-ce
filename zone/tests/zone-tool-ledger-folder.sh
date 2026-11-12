#!/bin/bash
# zone-tool ledger outside a checkout and inside a scratch checkout. Git's ceiling
# isolates the scratch folder; each invocation captures stdout and stderr separately.
# 1. Add writes the queued row in the non-git folder without errors.
# 2. Stage, add, first and ledger with no arguments show the requested order and worktree.
# 3. Close removes the row and records its worktree and timestamp.
# 4. Backlog defaults to the folder name.
# 5. Only the two ledger files exist in the non-git folder, with no .git.
# 6. A checkout subfolder writes at git top and updates info/exclude.
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
tmp="$(cd "$tmp" && pwd -P)"
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

folder="$tmp/zonefolder"; repo="$tmp/repo"
mkdir -p "$folder" "$repo/sub" || exit 2
git init -q "$repo" &&
  git -C "$repo" config user.name t && git -C "$repo" config user.email t@t &&
  git -C "$repo" config core.excludesFile "$tmp/empty-ignore" &&
  echo readme > "$repo/README" && git -C "$repo" add README &&
  git -C "$repo" commit -qm init || { echo "setup failed: scratch repo"; exit 2; }

out=""; err=""; rc=0
zt() {  # Each invocation is guarded before zone-tool can touch a working directory.
  local dir=$1 kind=$2; shift 2
  local top
  if [ "$kind" = folder ]; then
    if git -C "$dir" rev-parse --show-toplevel >/dev/null 2>&1; then
      echo "refusing zone-tool: $dir is in a git work tree"; exit 3
    fi
  else
    top="$(git -C "$dir" rev-parse --show-toplevel 2>/dev/null)"
    case "$top" in "$tmp"/*) ;; *) echo "refusing zone-tool: $dir has top [$top], outside $tmp"; exit 3;; esac
  fi
  (cd "$dir" && "$py" "$tool" "$@") > "$tmp/stdout" 2> "$tmp/stderr"; rc=$?
  out="$(cat "$tmp/stdout")"; err="$(cat "$tmp/stderr")"
}
check_run() {
  [ "$rc" -eq 0 ] || add_why "$1 exit $rc"
  [ -z "$err" ] || add_why "$1 stderr: $err"
}

zt "$folder" folder ledger add r1
check_run "ledger add r1"
printf 'r1 · queued · -\n' > "$tmp/want"
cmp -s "$folder/.ledger.md" "$tmp/want" || add_why "ledger does not contain exactly the queued r1 row"
finish "1 non-git add writes queued row"

zt "$folder" folder ledger stage r1 lead wtA
check_run "ledger stage r1 lead wtA"
zt "$folder" folder ledger add r2
check_run "ledger add r2"
zt "$folder" folder ledger first r2
check_run "ledger first r2"
zt "$folder" folder ledger
check_run "ledger list"
printf 'r2 · queued · -\nr1 · lead · wtA\n' > "$tmp/want"
cmp -s "$tmp/stdout" "$tmp/want" || add_why "ledger list does not show r2 then staged r1"
finish "2 stage add first and list"

zt "$folder" folder ledger close r1
check_run "ledger close r1"
grep -Eq '^r1 · wtA · [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}$' "$folder/.ledger-closed" 2>/dev/null || add_why "closed row with worktree and ISO minute missing"
if [ ! -f "$folder/.ledger.md" ] || grep -q '^r1 · ' "$folder/.ledger.md"; then
  add_why "open ledger missing or still contains r1"
fi
finish "3 close records and removes r1"

zt "$folder" folder backlog
check_run "backlog"
case "$out" in 'zonefolder: now r2 (stage: queued,'*) ;; *) add_why "backlog does not show zonefolder and r2: $out";; esac
finish "4 backlog defaults to folder name"

[ ! -e "$folder/.git" ] || add_why ".git was created"
printf '.ledger-closed\n.ledger.md\n' > "$tmp/want"
ls -A "$folder" > "$tmp/files"
cmp -s "$tmp/files" "$tmp/want" || add_why "folder does not contain exactly the two ledger files"
finish "5 only ledger files created without git"

zt "$repo/sub" repo ledger add s1
check_run "checkout ledger add s1"
printf 's1 · queued · -\n' > "$tmp/want"
cmp -s "$repo/.ledger.md" "$tmp/want" || add_why "git top ledger missing queued s1"
[ ! -e "$repo/sub/.ledger.md" ] || add_why "ledger incorrectly written in subfolder"
grep -qxF '/.ledger.md' "$repo/.git/info/exclude" || add_why "info/exclude lacks /.ledger.md"
finish "6 checkout subfolder uses git top and exclude"

echo "== zone-tool-ledger-folder: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
