#!/bin/bash
# Check make argument consumption and directory, variable and target decisions.
# slow: each case starts the real Python hook in a throwaway zoned repository.
root="$(cd "$(dirname "$0")/../.." && pwd)"
G="$root/share/claude-hooks/zone-guard.py"
T="$root/scratchpad/zone-guard-make-args-test-$$"
trap 'rm -rf "$T"' EXIT
W="$T/team-x/workcrews/AKit/repo-AKit"
mkdir -p "$T/team-x/team" "$W/packages/kits/AKit" "$W/packages/kits/BKit" "$T/non-lane"
export GIT_CEILING_DIRECTORIES="$(dirname "$W")"
git -C "$W" init -q
[ -d "$W/.git" ] || { echo '  FAIL setup: lane repo not created'; exit 1; }
echo '# AKit' > "$W/packages/kits/AKit/Makefile"
echo '# BKit' > "$W/packages/kits/BKit/Makefile"
git -C "$W" add -A && git -C "$W" -c user.email=t@t -c user.name=t commit -qm init || exit 1
echo '{"lanes": {"AKit": {"path": "packages/kits/AKit"}, "BKit": {"path": "packages/kits/BKit"}}}' > "$T/team-x/team/team.json"
for v in $(compgen -e); do case "$v" in CODETEAM_*|CT_*) unset "$v";; esac; done
export CODETEAM_WORKSPACE="$T"   # the throwaway team folder is in the workspace, so the guard applies
export CODETEAM_ZONE=packages/kits/AKit CODETEAM_SESSION=AKit CODETEAM_SWT="$W"
PASS=0; FAIL=0
run() {
  printf '{"tool_name":"Bash","tool_input":{"command":"%s"},"cwd":"%s"}\n' "$1" "${2:-$W}" |
    python3 "$G" pretool > /dev/null 2> "$T/stderr"
  got=$?
}
expect() {
  run "$2" "$3"
  if [ "$got" -eq "$1" ]; then PASS=$((PASS+1)); echo "  PASS $4"
  else FAIL=$((FAIL+1)); echo "  FAIL $4 (exit $got, wanted $1)"; fi
}
# Compares the deny reason (between the hook's prefix and its zone suffix) with $4 exactly.
expect_msg() {
  run "$2" "$3"
  local s why=
  s=$(cat "$T/stderr")
  if [ "${s#Zone guard: }" != "$s" ]; then
    why=${s#Zone guard: }
    why=${why%" is outside zone \`packages/kits/AKit\` (AKit lane). "*}
  fi
  if [ "$got" -eq "$1" ] && [ "$why" = "$4" ]; then
    PASS=$((PASS+1)); echo "  PASS $5"
  else
    FAIL=$((FAIL+1)); echo "  FAIL $5 (exit $got, wanted $1; expected: $4; got: $why)"
  fi
}
expect 0 'make -C packages/kits/AKit build' '' '-C separate own Makefile'
expect 0 'make -Cpackages/kits/AKit build' '' '-C attached own Makefile'
expect 0 'make --directory packages/kits/AKit build' '' '--directory separate own Makefile'
expect 0 'make --directory=packages/kits/AKit build' '' '--directory equals own Makefile'
expect 2 'make -C packages/kits/BKit build' '' '-C separate other zone'
expect 2 'make -Cpackages/kits/BKit build' '' '-C attached other zone'
expect 2 'make --directory packages/kits/BKit build' '' '--directory separate other zone'
expect 2 'make --directory=packages/kits/BKit build' '' '--directory equals other zone'
expect 0 'make -C /tmp build' '' '-C unprotected directory'
expect 2 "make -C $T/non-lane build" '' '-C protected non-lane directory'
expect 0 'make -C packages/kits/BKit -C ../AKit build' '' 'repeated -C resolves relative to previous directory'
expect 2 'make build -C' '' 'trailing -C leaves build as target'
expect 0 'make build' "$W/packages/kits/AKit" 'cwd in zone uses its Makefile'
expect 0 'make -f build zone-test-one' '' '-f consumes next word'
expect 0 'make --file build zone-test-one' '' '--file consumes next word'
expect 0 'make --makefile build zone-test-one' '' '--makefile consumes next word'
expect 0 'make -o build zone-test-one' '' '-o consumes next word'
expect 0 'make -W build zone-test-one' '' '-W consumes next word'
expect 0 'make -I build zone-test-one' '' '-I consumes next word'
expect 0 'make --include-dir build zone-test-one' '' '--include-dir consumes next word'
expect 2 'make -f x.mk build' '' '-f leaves following build as target'
expect 2 'make build -f' '' 'trailing -f leaves build as target'
expect 2 'make build -I' '' 'trailing -I leaves build as target'
expect 0 'make -j 4 zone-test-one' '' '-j consumes digit'
expect 0 'make -l 2 zone-test-one' '' '-l consumes digit'
expect 2 'make -j build' '' '-j leaves nondigit build as target'
expect 0 'make -n build' '' '-n before target is print-only'
expect 0 'make build -n' '' '-n after target is print-only'
expect 0 'make -q build' '' '-q is print-only'
expect 2 'make -p ZONE_TEST=x build' '' '-p locked variable refused'
expect 2 'make --print-data-base ZONE_TEST=x build' '' '--print-data-base locked variable refused'
expect_msg 2 'make -p build' '' 'make target `build` (a whole-product target; lanes run make zone-test, zone-test-one, zone-test-status, zone-check DIR=<zone>, warm, test-one DIR=<zone>)' '-p whole-product target refused'
expect 0 'make -p build' "$W/packages/kits/AKit" '-p cwd in zone allowed'
expect 2 'make -f -n build' '' '-f consumes -n before print-only check'
expect 2 'make zone-test-one ZONE_TEST=x' '' 'ZONE_TEST assignment refused'
expect 2 'make zone-test-one ZONE_ROOT:=x' '' 'ZONE_ROOT immediate assignment refused'
expect 2 'make zone-test-one ZONE_TOOL+=x' '' 'ZONE_TOOL append assignment refused'
expect 2 'ZONE_TOOL=x make zone-test-one' '' 'ZONE_TOOL environment prefix refused'
expect 2 'make zone-test-one ZONE=packages/kits/BKit' '' 'other ZONE refused'
expect 0 'make zone-test-one ZONE=packages/kits/AKit/' '' 'own ZONE trailing slash allowed'
# DIR containing $ bypasses target checks, but not the earlier variable or lane-copy checks.
expect 0 "make build DIR='\$X'" '' 'variable DIR bypasses target check today'
expect 2 "make build DIR='\$X' ZONE_TOOL=x" '' 'locked variable checked before variable DIR'
expect 2 "make -C $T/non-lane build DIR='\$X'" '' 'lane copy checked before variable DIR'
expect_msg 2 "make -C $T/non-lane build" '' "make in \`$(cd "$T/non-lane" && pwd -P)\` (not one of this lane's worktrees)" 'non-lane directory refusal text'
expect_msg 2 'make zone-test-one ZONE_TOOL=x' '' 'make with ZONE_TOOL= (it would let a zone target run other code)' 'ZONE_TOOL refusal text'
expect_msg 2 'make zone-test-one ZONE_TEST=x' '' 'make with ZONE_TEST= (it would let a zone target run other code)' 'ZONE_TEST refusal text'
expect_msg 2 'make zone-test-one ZONE=packages/kits/BKit' '' 'make ZONE=packages/kits/BKit' 'ZONE refusal text'
expect_msg 2 'make zone-test-one DIR=packages/kits/BKit' '' 'make DIR=packages/kits/BKit' 'relative DIR refusal text'
expect_msg 2 "make zone-test-one DIR=$T/non-lane" '' "make DIR=$T/non-lane" 'absolute DIR refusal text'
expect_msg 2 'make build' '' 'make target `build` (a whole-product target; lanes run make zone-test, zone-test-one, zone-test-status, zone-check DIR=<zone>, warm, test-one DIR=<zone>)' 'whole-product target refusal text'
echo "== zone-guard-make-args: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
