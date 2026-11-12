#!/bin/bash
# zone/tests/zone-guard-doc-exception.sh: the zone guard's subagent notice (zone-guard.py `subagent`, the
# SubagentStart rule_text) names the zone's own SPEC and INTERFACE exception with the fixed phrase "in `docs/reference` or `docs/internal/reference` and their `docs/_public` copies" (the
# DOC_EXCEPTION constant, used by the two zoned branches only). Checks a zoned lane (AKit, zone
# packages/kits/AKit) on two team folders, team-x and team-acme. Control: both notices are non-empty and name "You work for the AKit lane", so a broken
# setup cannot pass the phrase checks by accident. Runs the worktree's own zone-guard.py by its own path
# (never $CODETEAM_HOME), in a throwaway folder under scratchpad/ that is removed on exit. Three checks,
# two python3 runs for the guard: well under a second. No sleeps, no network.
root="$(cd "$(dirname "$0")/../.." && pwd)"
G="$root/share/claude-hooks/zone-guard.py"
T="$root/scratchpad/zone-guard-doc-exception-test-$$"
trap 'rm -rf "$T"' EXIT
rm -rf "$T"
# Same result from a lane session as from a plain shell: clear every CODETEAM_* and CT_* the caller
# exported, then set the lane's own facts per run (zone-guard-orc-owns.sh does the same).
for v in $(compgen -e); do case "$v" in CODETEAM_*|CT_*) unset "$v";; esac; done
mkdir -p "$T/team-x/workcrews/AKit/repo-AKit/packages/kits/AKit" \
  "$T/team-acme/workcrews/AKit/repo-AKit/packages/kits/AKit" "$T/home"
export GIT_CEILING_DIRECTORIES="$T"
export CODETEAM_BIN=/usr/bin/true
export CODETEAM_HOME="$T/home"
# The fixed phrase. Backticks escaped.
PHRASE=", plus your zone's own SPEC and INTERFACE in \`docs/reference\` or \`docs/internal/reference\` and their \`docs/_public\` copies"
# The subagent notice for the AKit lane in the team folder $1 (the product is the folder's name after team-).
notice() {
  printf '{}' | CODETEAM_SWT="$1/workcrews/AKit/repo-AKit" CODETEAM_SESSION=AKit CODETEAM_ZONE=packages/kits/AKit \
    python3 "$G" subagent
}
TEAM_X="$(notice "$T/team-x")"
TEAM_ACME="$(notice "$T/team-acme")"
PASS=0; FAIL=0
row() {   # $1 = 0 when the check passed, $2 = the row's name
  if [ "$1" = 0 ]; then PASS=$((PASS+1)); echo "  PASS $2"; else FAIL=$((FAIL+1)); echo "  FAIL $2"; fi
}
if printf '%s' "$TEAM_X" | grep -qF -- "$PHRASE"; then r=0; else r=1; fi
row $r "zoned team-x: the subagent notice names the SPEC and INTERFACE exception in docs/reference or docs/internal/reference"
if printf '%s' "$TEAM_ACME" | grep -qF -- "$PHRASE"; then r=0; else r=1; fi
row $r "zoned team-acme: the subagent notice names the SPEC and INTERFACE exception in docs/reference or docs/internal/reference"
if [ -n "$TEAM_X" ] && [ -n "$TEAM_ACME" ] \
  && printf '%s' "$TEAM_X" | grep -qF -- "You work for the AKit lane" \
  && printf '%s' "$TEAM_ACME" | grep -qF -- "You work for the AKit lane"; then r=0; else r=1; fi
row $r "control: both subagent notices are non-empty and name 'You work for the AKit lane'"
echo "== zone-guard-doc-exception: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
