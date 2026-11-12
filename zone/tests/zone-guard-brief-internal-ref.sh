#!/bin/bash
# zone/tests/zone-guard-brief-internal-ref.sh: the zone brief (zone-guard.py `start`, an active zone lane) names
# the zone's SPEC and INTERFACE from docs/reference and docs/internal/reference: the owned files
# of docs/reference/*.md (sorted), then the owned files of docs/internal/reference/*.md (sorted), each by its
# repo-relative path, in one line "Your zone's SPEC and INTERFACE: `a`, `b`.". docs/_public/reference is never
# listed, and with docs/internal/reference empty the line is the docs/reference part alone. Checks a lane Widget
# (zone packages/Widget) on a team folder named team-x, whose team/team.json also names a lane Gadget
# (packages/Gadget): GADGET_INTERFACE.md is another lane's file and must not be listed (AKit is not used: its
# "Kit" stem strip would match too much). Row 4 is a second team folder, team-y, with docs/internal/reference
# empty. Row 5 is the control: both briefs are non-empty and carry the zone's heading, so a broken setup cannot
# pass rows 2-4 by accident. Runs the worktree's own zone-guard.py by its own path (never $CODETEAM_HOME), in
# mode `start` with source "startup" (never "compact": that writes the lane's state), in a throwaway folder under
# scratchpad/ that is removed on exit. HOME is a scratch folder too, since the guard logs to $HOME/.claude/audit.
# Five checks on two briefs, one python3 run of the guard per brief: well under a second. No sleeps, no network.
root="$(cd "$(dirname "$0")/../.." && pwd)"
G="$root/share/claude-hooks/zone-guard.py"
T="$root/scratchpad/zone-guard-brief-internal-ref-test-$$"
trap 'rm -rf "$T"' EXIT
rm -rf "$T"
# Same result from a lane session as from a plain shell: clear every CODETEAM_* and CT_* the caller
# exported, then set the lane's own facts per run (zone-guard-doc-exception.sh does the same).
for v in $(compgen -e); do case "$v" in CODETEAM_*|CT_*) unset "$v";; esac; done
mkdir -p "$T/userhome" "$T/codeteam-home"
export HOME="$T/userhome"
export GIT_CEILING_DIRECTORIES="$T"
export CODETEAM_BIN=/usr/bin/true
export CODETEAM_HOME="$T/codeteam-home"
export PYTHONDONTWRITEBYTECODE=1
# A team folder $1 (named team-<product>) with the Widget lane's worktree: the reference docs of the full
# case (docs/internal/reference holds the Widget and the Gadget interface), and team/team.json naming both lanes.
make_team() {
  local team="$1" w="$1/workcrews/Widget/repo-Widget"
  mkdir -p "$team/team" "$w/packages/Widget" "$w/packages/Gadget" "$w/docs/reference" \
    "$w/docs/internal/reference" "$w/docs/_public/reference"
  printf '%s\n' '{"lanes": {"Widget": {"path": "packages/Widget"}, "Gadget": {"path": "packages/Gadget"}}}' \
    > "$team/team/team.json"
  printf '# Widget spec\n' > "$w/docs/reference/WIDGET_SPEC.md"
  printf '# Widget interface\n' > "$w/docs/internal/reference/WIDGET_INTERFACE.md"
  printf '# Gadget interface\n' > "$w/docs/internal/reference/GADGET_INTERFACE.md"
  printf '# Widget spec, public copy\n' > "$w/docs/_public/reference/WIDGET_SPEC.md"
}
make_team "$T/team-x"
# The same team with docs/internal/reference empty (row 4).
make_team "$T/team-y"
rm -f "$T/team-y/workcrews/Widget/repo-Widget/docs/internal/reference/"*.md
# The zone brief for the Widget lane in the team folder $1: the guard's `start` mode, source "startup".
brief() {
  printf '%s' '{"source":"startup"}' | CODETEAM_SWT="$1/workcrews/Widget/repo-Widget" CODETEAM_SESSION=Widget \
    CODETEAM_ZONE=packages/Widget python3 "$G" start
}
FULL="$(brief "$T/team-x")"
EMPTY="$(brief "$T/team-y")"
# The sentences (backticks escaped). Each must be a whole line of the brief.
FULL_SENT="Your zone's SPEC and INTERFACE: \`docs/reference/WIDGET_SPEC.md\`, \`docs/internal/reference/WIDGET_INTERFACE.md\`."
ONLY_SENT="Your zone's SPEC and INTERFACE: \`docs/reference/WIDGET_SPEC.md\`."
PASS=0; FAIL=0
row() {   # $1 = 0 when the check passed, $2 = the row's name
  if [ "$1" = 0 ]; then PASS=$((PASS+1)); echo "  PASS $2"; else FAIL=$((FAIL+1)); echo "  FAIL $2"; fi
}
if printf '%s\n' "$FULL" | grep -qxF -- "$FULL_SENT"; then r=0; else r=1; fi
row $r "zone brief: the SPEC and INTERFACE line is exactly the docs/reference files, then the docs/internal/reference files"
if printf '%s' "$FULL" | grep -qF -- "GADGET_INTERFACE"; then r=1; else r=0; fi
row $r "zone brief: another lane's GADGET_INTERFACE.md is not named"
if printf '%s' "$FULL" | grep -qF -- "docs/_public/reference" || printf '%s' "$EMPTY" | grep -qF -- "docs/_public/reference"; then r=1; else r=0; fi
row $r "zone brief: docs/_public/reference is never named (full and empty-internal briefs)"
if printf '%s\n' "$EMPTY" | grep -qxF -- "$ONLY_SENT"; then r=0; else r=1; fi
row $r "empty docs/internal/reference: the SPEC and INTERFACE line is exactly the docs/reference part"
if [ -n "$FULL" ] && [ -n "$EMPTY" ] \
  && printf '%s' "$FULL" | grep -qF -- '## Your zone: `packages/Widget`' \
  && printf '%s' "$EMPTY" | grep -qF -- '## Your zone: `packages/Widget`'; then r=0; else r=1; fi
row $r "control: both zone briefs are non-empty and carry '## Your zone: \`packages/Widget\`'"
echo "== zone-guard-brief-internal-ref: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
