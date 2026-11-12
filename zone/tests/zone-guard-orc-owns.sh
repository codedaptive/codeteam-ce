#!/bin/bash
# zone/tests/zone-guard-orc-owns.sh: the zone guard refuses an edit to a path the manifest's
# top-level `orchestrator_owns` names for a zoned lane (AKit, its own
# zone file) and a walled lane (gauges, zone ".", a tracked file at the top). Controls: the same edits
# are allowed when CODETEAM_MANIFEST points at a TOML without the key, and at a path that does not
# exist. And a zoned lane's `git add docs/internal` (the parent of the owned reference folder,
# with docs/internal/reference/ in the scratch repo) is not refused (zone-guard.py holds_zone).
# Runs zone-guard.py's pretool mode on a throwaway team folder under scratchpad/, as
# zone-guard-case.sh does, so the guard applies; the folder is removed on exit. Seven checks, each
# a fresh python3 for the guard, plus one git setup: a few seconds at most. No sleeps, no network.
root="$(cd "$(dirname "$0")/../.." && pwd)"
G="$root/share/claude-hooks/zone-guard.py"
T="$root/scratchpad/zone-guard-orc-owns-test-$$"
trap 'rm -rf "$T"' EXIT
rm -rf "$T"
# Same result from a lane session as from a plain shell: clear every CODETEAM_* and CT_* the caller
# exported, then set the lane's own facts per check (zone-guard-case.sh does the same).
for v in $(compgen -e); do case "$v" in CODETEAM_*|CT_*) unset "$v";; esac; done
export CODETEAM_WORKSPACE="$T"   # the throwaway team folder is in the workspace, so the guard applies
L="$T/team-x/workcrews/AKit"; W="$L/repo-AKit"
mkdir -p "$T/team-x/team" "$W/packages/kits/AKit/Sources" "$W/packages/kits/BKit/Sources" \
  "$W/docs/internal/reference" "$T/team-x/workcrews/BKit/scratchpad"
export GIT_CEILING_DIRECTORIES="$T"
git -C "$W" init -q
echo x > "$W/README"
echo x > "$W/packages/kits/AKit/Sources/x.swift"
echo x > "$W/packages/kits/BKit/Sources/x.swift"
echo x > "$W/docs/internal/reference/AKIT_SPEC.md"
git -C "$W" add -A; git -C "$W" -c user.email=t@t -c user.name=t commit -qm init
git -C "$W" ls-files --error-unmatch README packages/kits/AKit/Sources/x.swift packages/kits/BKit/Sources/x.swift \
  docs/internal/reference/AKIT_SPEC.md >/dev/null 2>&1 \
  || { echo "  FAIL setup: lane repo not created"; exit 1; }
echo '{"lanes": {"AKit": {"path": "packages/kits/AKit"}, "BKit": {"path": "packages/kits/BKit"}, "gauges": {"path": ".", "owns": []}}}' > "$T/team-x/team/team.json"
# The manifests: one with the key (top level, before the [[lanes]] table), one without it.
cat > "$T/orc.toml" <<'TOML'
product = "codeteam"
orchestrator_owns = ["packages/kits/AKit/Sources/x.swift", "README"]

[[lanes]]
name = "AKit"
path = "packages/kits/AKit"
TOML
cat > "$T/no-key.toml" <<'TOML'
product = "codeteam"

[[lanes]]
name = "AKit"
path = "packages/kits/AKit"
TOML
MISSING="$T/no-such-manifest.toml"
export CODETEAM_SWT="$W" CODETEAM_HOME="$root"
PASS=0; FAIL=0
run() { echo "{\"tool_name\":\"$1\",\"tool_input\":$2,\"cwd\":\"$W\"}" | python3 "$G" pretool >/dev/null 2>&1; echo $?; }
expect() { got=$(run "$2" "$3"); if [ "$got" = "$1" ]; then PASS=$((PASS+1)); echo "  PASS $4"; else FAIL=$((FAIL+1)); echo "  FAIL $4 (exit $got, wanted $1)"; fi; }
# Zoned lane: AKit, zone packages/kits/AKit. Its own file, listed by orchestrator_owns, is refused.
CODETEAM_MANIFEST="$T/orc.toml" CODETEAM_ZONE=packages/kits/AKit CODETEAM_SESSION=AKit expect 2 Edit "{\"file_path\":\"$W/packages/kits/AKit/Sources/x.swift\"}" "zoned: an edit to packages/kits/AKit/Sources/x.swift, which orchestrator_owns names, is refused"
# Walled lane: gauges, zone "."; README is a tracked file at the top that it otherwise owns.
CODETEAM_MANIFEST="$T/orc.toml" CODETEAM_ZONE=. CODETEAM_SESSION=gauges expect 2 Edit "{\"file_path\":\"$W/README\"}" "walled: an edit to README, which orchestrator_owns names, is refused"
# Controls: the same edits are allowed without the key and with no manifest at that path.
CODETEAM_MANIFEST="$T/no-key.toml" CODETEAM_ZONE=packages/kits/AKit CODETEAM_SESSION=AKit expect 0 Edit "{\"file_path\":\"$W/packages/kits/AKit/Sources/x.swift\"}" "zoned control: the same edit is allowed with a manifest that has no orchestrator_owns"
CODETEAM_MANIFEST="$T/no-key.toml" CODETEAM_ZONE=. CODETEAM_SESSION=gauges expect 0 Edit "{\"file_path\":\"$W/README\"}" "walled control: the same README edit is allowed with a manifest that has no orchestrator_owns"
CODETEAM_MANIFEST="$MISSING" CODETEAM_ZONE=packages/kits/AKit CODETEAM_SESSION=AKit expect 0 Edit "{\"file_path\":\"$W/packages/kits/AKit/Sources/x.swift\"}" "zoned control: the same edit is allowed with a manifest path that does not exist"
CODETEAM_MANIFEST="$MISSING" CODETEAM_ZONE=. CODETEAM_SESSION=gauges expect 0 Edit "{\"file_path\":\"$W/README\"}" "walled control: the same README edit is allowed with a manifest path that does not exist"
# staging the parent of the owned reference folder is not refused for a zoned lane.
CODETEAM_MANIFEST="$T/no-key.toml" CODETEAM_ZONE=packages/kits/AKit CODETEAM_SESSION=AKit expect 0 Bash "{\"command\":\"git add docs/internal\"}" "zoned: git add docs/internal (the parent of docs/internal/reference) is not refused"
echo "== zone-guard-orc-owns: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
