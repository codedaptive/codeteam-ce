#!/bin/bash
# zone-guard-zone-check: exercise allowed and refused DIR values for a zoned lane;
# check that refusals name the missing DIR and suggest zone-check for a product build.
# About 1 s: ten guard invocations and a throwaway git repository; no sleeps.
root="$(cd "$(dirname "$0")/../.." && pwd)"
G="$root/share/claude-hooks/zone-guard.py"
T="$root/scratchpad/zone-guard-zone-check-test-$$"
trap 'rm -rf "$T"' EXIT
W="$T/team-x/workcrews/AKit/repo-AKit"
mkdir -p "$T/team-x/team" "$W/packages/kits/AKit/rust" "$W/packages/kits/BKit"
export GIT_CEILING_DIRECTORIES="$(dirname "$W")"
git -C "$W" init -q
[ -d "$W/.git" ] || { echo '  FAIL setup: lane repo not created'; exit 1; }
echo x > "$W/packages/kits/AKit/tracked"
echo x > "$W/packages/kits/BKit/tracked"
git -C "$W" add -A && git -C "$W" -c user.email=t@t -c user.name=t commit -qm init || exit 1
echo '{"lanes": {"AKit": {"path": "packages/kits/AKit"}, "BKit": {"path": "packages/kits/BKit"}}}' > "$T/team-x/team/team.json"
for v in $(compgen -e); do case "$v" in CODETEAM_*|CT_*) unset "$v";; esac; done
export CODETEAM_WORKSPACE="$T"   # the throwaway team folder is in the workspace, so the guard applies
export CODETEAM_ZONE=packages/kits/AKit CODETEAM_SESSION=AKit CODETEAM_SWT="$W"
PASS=0; FAIL=0
run() {
  printf '{"tool_name":"Bash","tool_input":{"command":"%s"},"cwd":"%s"%s}\n' "$1" "$W" "$2" |
    python3 "$G" pretool > /dev/null 2> "$T/stderr"
  got=$?
}
expect() {
  run "$2" "$3"
  if [ "$got" -eq "$1" ]; then PASS=$((PASS+1)); echo "  PASS $4"
  else FAIL=$((FAIL+1)); echo "  FAIL $4 (exit $got, wanted $1)"; fi
}
expect 0 'make zone-check DIR=packages/kits/AKit' '' 'zone DIR is allowed'
expect 0 'make zone-check DIR=packages/kits/AKit/rust' '' 'nested DIR is allowed'
expect 0 'make zone-check DIR=packages/kits/AKit' ',"agent_id":"a1"' 'subagent zone DIR is allowed'
expect 2 'make zone-check DIR=packages/kits/BKit' '' 'other zone DIR is refused'
expect 2 'make zone-check DIR=.' '' 'product root DIR is refused'
expect 2 'make zone-check DIR=' '' 'empty DIR is refused'
expect 2 "make zone-check DIR=$W/packages/kits/BKit" '' 'absolute other zone DIR is refused'
expect 2 'make zone-check' '' 'bare zone-check is refused'
run 'make zone-check' ''
if [ "$got" -eq 2 ] && grep -Fq 'zone-check without DIR=' "$T/stderr"; then
  PASS=$((PASS+1)); echo '  PASS bare zone-check refusal says it lacks DIR='
else
  FAIL=$((FAIL+1)); echo "  FAIL bare zone-check refusal says it lacks DIR= (exit $got)"
fi
run 'make build' ''
if [ "$got" -eq 2 ] && grep -Fq 'zone-check DIR=' "$T/stderr"; then
  PASS=$((PASS+1)); echo '  PASS product build refusal names zone-check DIR='
else
  FAIL=$((FAIL+1)); echo "  FAIL product build refusal names zone-check DIR= (exit $got)"
fi
echo "== zone-guard-zone-check: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
