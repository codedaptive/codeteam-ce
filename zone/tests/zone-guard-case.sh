#!/bin/bash
# zone/tests/zone-guard-case.sh: the zone guard's pretool mode refuses a path whose top folder
# differs only in case from a tracked one (`PACKAGES/kits/AKit/...` for `packages/...`), for a
# walled lane (gauges, zone ".") and a zoned lane (AKit). A real untracked file at the top
# (status.md) stays the lane's own, and the exact-case controls stay as they are.
# Runs zone-guard.py's pretool mode on a throwaway team folder inside CODETEAM_WORKSPACE, so the guard
# applies; the folder is removed on exit. About 1 s: 11 checks each start a fresh python3 for
# the guard, which runs git itself, and setup git-inits and commits one repository. No sleeps.
root="$(cd "$(dirname "$0")/../.." && pwd)"
G="$root/share/claude-hooks/zone-guard.py"
T="$root/scratchpad/zone-guard-case-test-$$"
trap 'rm -rf "$T"' EXIT
rm -rf "$T"
# Same result from a lane session as from a plain shell: clear every CODETEAM_* and CT_* the caller
# exported, then set the lane's own facts per check (tests/zone-guard.sh:18-21 does the same).
for v in $(compgen -e); do case "$v" in CODETEAM_*|CT_*) unset "$v";; esac; done
export CODETEAM_WORKSPACE="$T"   # the throwaway team folder is in the workspace, so the guard applies
L="$T/team-x/workcrews/AKit"; W="$L/repo-AKit"
mkdir -p "$T/team-x/team" "$W/packages/kits/AKit/Sources" "$W/packages/kits/BKit/Sources" "$T/team-x/workcrews/BKit/scratchpad"
export GIT_CEILING_DIRECTORIES="$T"
git -C "$W" init -q
echo x > "$W/README"
echo x > "$W/packages/kits/AKit/Sources/x.swift"
echo x > "$W/packages/kits/BKit/Sources/x.swift"
git -C "$W" add -A; git -C "$W" -c user.email=t@t -c user.name=t commit -qm init
git -C "$W" ls-files --error-unmatch README packages/kits/AKit/Sources/x.swift packages/kits/BKit/Sources/x.swift >/dev/null 2>&1 \
  || { echo "  FAIL setup: lane repo not created"; exit 1; }
echo '{"lanes": {"AKit": {"path": "packages/kits/AKit"}, "BKit": {"path": "packages/kits/BKit"}, "gauges": {"path": ".", "owns": []}}}' > "$T/team-x/team/team.json"
export CODETEAM_SWT="$W"
PASS=0; FAIL=0
run() { echo "{\"tool_name\":\"$1\",\"tool_input\":$2,\"cwd\":\"$W\"}" | python3 "$G" pretool >/dev/null 2>&1; echo $?; }
expect() { got=$(run "$2" "$3"); if [ "$got" = "$1" ]; then PASS=$((PASS+1)); echo "  PASS $4"; else FAIL=$((FAIL+1)); echo "  FAIL $4 (exit $got, wanted $1)"; fi; }
# Walled lane: gauges, zone "." beside AKit and BKit.
CODETEAM_ZONE=. CODETEAM_SESSION=gauges expect 2 Edit "{\"file_path\":\"$W/PACKAGES/kits/AKit/Sources/x.swift\"}" "walled: an edit under PACKAGES/kits/AKit (top folder case variant) is refused"
CODETEAM_ZONE=. CODETEAM_SESSION=gauges expect 2 Bash "{\"command\":\"echo x > Packages/Kits/BKit/notes.md\"}" "walled: a shell write under Packages/Kits/BKit (top folder case variant) is refused"
CODETEAM_ZONE=. CODETEAM_SESSION=gauges expect 2 Edit "{\"file_path\":\"$W/packages/KITS/AKit/Sources/x.swift\"}" "walled control: a deep case variant of another lane's folder is refused"
CODETEAM_ZONE=. CODETEAM_SESSION=gauges expect 0 Edit "{\"file_path\":\"$W/status.md\"}" "walled: an untracked file at the top (status.md) is the lane's own"
CODETEAM_ZONE=. CODETEAM_SESSION=gauges expect 2 Edit "{\"file_path\":\"$W/packages/kits/AKit/Sources/x.swift\"}" "walled control: an exact-case edit in AKit's folder is refused"
# Zoned lane: AKit, zone packages/kits/AKit.
CODETEAM_ZONE=packages/kits/AKit CODETEAM_SESSION=AKit expect 2 Edit "{\"file_path\":\"$W/PACKAGES/kits/BKit/Sources/x.swift\"}" "zoned: an edit under PACKAGES/kits/BKit (top folder case variant) is refused"
CODETEAM_ZONE=packages/kits/AKit CODETEAM_SESSION=AKit expect 2 Bash "{\"command\":\"echo x > PACKAGES/kits/BKit/notes.md\"}" "zoned: a shell write under PACKAGES/kits/BKit (top folder case variant) is refused"
CODETEAM_ZONE=packages/kits/AKit CODETEAM_SESSION=AKit expect 2 Edit "{\"file_path\":\"$W/PACKAGES/kits/AKit/Sources/x.swift\"}" "zoned: an edit to its own zone under a misspelled top folder is refused"
CODETEAM_ZONE=packages/kits/AKit CODETEAM_SESSION=AKit expect 2 Edit "{\"file_path\":\"$W/readme\"}" "zoned: a case variant of the tracked README (no lane owns it) is refused"
CODETEAM_ZONE=packages/kits/AKit CODETEAM_SESSION=AKit expect 0 Edit "{\"file_path\":\"$W/status.md\"}" "zoned: an untracked file at the top (status.md) is the lane's own"
CODETEAM_ZONE=packages/kits/AKit CODETEAM_SESSION=AKit expect 0 Edit "{\"file_path\":\"$W/packages/kits/AKit/Sources/x.swift\"}" "zoned control: an edit in its own zone is allowed"
echo "== zone-guard-case: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
