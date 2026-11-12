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
exit $fail
