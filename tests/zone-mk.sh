#!/bin/bash
# zone.mk: zone-test and zone-test-one record nothing under make -n, -t or -q.
# zone-test and zone-test-one submit to the build queue with their class: checks 15 to 17.
set -u
# A session exports MAKEFILES (the live zone.mk), which make would read before the include below.
# A caller's CLASS (a runner's own class) would pick the class checks 15 to 17 read.
unset MAKEFILES CLASS
# Stage 2 (v5.2) sets GROUP and CODETEAM_TEST_GROUP: children must not inherit them or their record keys change.
# export -n keeps the outer values available to this script without exporting them.
export -n GROUP CODETEAM_TEST_GROUP
HERE=$(cd "$(dirname "$0")/.." && pwd)
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
cat > "$W/zone-tool" <<'T'
#!/bin/bash
echo "$*" >> "$MARK"
T
chmod +x "$W/zone-tool"
cat > "$W/Makefile" <<M
include $HERE/zone/zone.mk
test-one:
	@true
M
fail=0
run() {  # $1 label, $2 expect (rec|none), rest: make args
  local label=$1 want=$2; shift 2
  export MARK="$W/mark.$label"; rm -f "$MARK"
  make -C "$W" --no-print-directory ZONE_TOOL="$W/zone-tool" ZONE_ROOT="$W" ZONE=z ZONE_TEST=true "$@" >/dev/null 2>&1
  local got=none; [ -s "$MARK" ] && got=rec
  if [ "$got" = "$want" ]; then echo "ok   $label"; else echo "FAIL $label: want $want, got $got"; fail=1; fi
}
for tgt in zone-test "zone-test-one DIR=pkg"; do
  t=${tgt%% *}
  run "$t-plain" rec $tgt
  run "$t-n" none -n $tgt
  run "$t-t" none -t $tgt
  run "$t-q" none -q $tgt
  run "$t-dry-run" none --dry-run $tgt
  run "$t-ignore-n-in-value" rec $tgt CARGO_TEST_ARGS=-n
  run "$t-s" rec -s $tgt
done
# The stub records the arguments make gave zone-tool: the target's class.
n=0
args_has() {  # $1 label, $2 text the arguments must hold, rest: make args
  local label=$1 text=$2; shift 2
  n=$((n+1)); export MARK="$W/args.$n"; rm -f "$MARK"
  make -C "$W" --no-print-directory ZONE_TOOL="$W/zone-tool" ZONE_ROOT="$W" ZONE=z ZONE_TEST=true "$@" >/dev/null 2>&1
  if grep -q -- "$text" "$MARK" 2>/dev/null; then echo "ok   $label"; else echo "FAIL $label: zone-tool got [$(cat "$MARK" 2>/dev/null)]"; fail=1; fi
}
args_has "15 zone-test submits class full" "job submit --class full" zone-test
args_has "16 zone-test-one submits class dev" "job submit --class dev" zone-test-one DIR=pkg
args_has "17 zone-test-one with CLASS=post submits class post" "job submit --class post" zone-test-one DIR=pkg CLASS=post
# warm in a tree whose session names no lane worktree and no exchange (an orchestrator's or a staff session's work
# order tree): it warms from the tree itself, where zone-tool keeps a build already there or clones the freshest
# sibling tree's, instead of refusing.
warm_check() {  # $1 label, $2 text zone-tool's arguments must hold, $3 CODETEAM_SWT (empty: unset)
  n=$((n+1)); export MARK="$W/args.$n"; rm -f "$MARK"
  local out rc
  out=$(env -u CODETEAM_SWT -u CODETEAM_EXCHANGE -u EXCHANGE -u WARM_FROM ${3:+CODETEAM_SWT=$3} \
    make -C "$W" --no-print-directory ZONE_TOOL="$W/zone-tool" ZONE_ROOT="$W" WARM_BUILD=0 warm 2>&1); rc=$?
  if [ "$rc" = 0 ] && grep -q -- "$2" "$MARK" 2>/dev/null; then echo "ok   $1"
  else echo "FAIL $1: exit $rc, output [$out], zone-tool got [$(cat "$MARK" 2>/dev/null)]"; fail=1; fi
}
warm_check "18 warm with no lane worktree or exchange warms from the tree itself" "warm --from $W --target cargo-target" ""
warm_check "19 warm in a lane session warms from the lane's worktree" "warm --from /x/lane --target cargo-target" /x/lane
# Opt-in variables: each name in ZONE_TEST_KEY_VARS that is set adds env:NAME=value to
# zone-test-one's key and zone-test's salt, so a run with it on is never answered by a record made with it off.
unset ACME_X
args_of() {  # rest: make args; prints the arguments make gave zone-tool
  n=$((n+1)); export MARK="$W/args.$n"; rm -f "$MARK"
  make -C "$W" --no-print-directory ZONE_TOOL="$W/zone-tool" ZONE_ROOT="$W" ZONE=z ZONE_TEST=true "$@" >/dev/null 2>&1
  cat "$MARK" 2>/dev/null
}
expect() {  # $1 label, rest: a test command
  local label=$1; shift
  if "$@"; then echo "ok   $label"; else echo "FAIL $label"; fail=1; fi
}
has() { case "$1" in *"$2"*) return 0;; esac; return 1; }
plain=$(args_of zone-test-one DIR=pkg)
expect "20 a named variable left unset keeps the key byte for byte" \
  test "$plain" = "$(args_of zone-test-one DIR=pkg ZONE_TEST_KEY_VARS=ACME_X)"
expect "21 set on make's command line, it keys the record" \
  has "$(args_of zone-test-one DIR=pkg ZONE_TEST_KEY_VARS=ACME_X ACME_X=1)" "--key one pkg   env:ACME_X=1 "
export ACME_X=1
expect "22 set in the environment, it keys the record too" \
  has "$(args_of zone-test-one DIR=pkg ZONE_TEST_KEY_VARS=ACME_X)" "env:ACME_X=1"
unset ACME_X
printf 'include %s/zone/zone.mk\nZONE_TEST_KEY_VARS = ACME_X\ntest-one:\n\t@true\n' "$HERE" > "$W/Makefile.decl"
expect "23 the repo's own Makefile can name it, after zone.mk" \
  has "$(args_of -f Makefile.decl zone-test-one DIR=pkg ACME_X=1)" "env:ACME_X=1"
expect "24 zone-test gets no salt without it" eval '! has "$(args_of zone-test ZONE_TEST_KEY_VARS=ACME_X)" "--salt"'
expect "25 and the word as its salt with it" \
  has "$(args_of zone-test ZONE_TEST_KEY_VARS=ACME_X ACME_X=1)" "--salt env:ACME_X=1 "
exit $fail
