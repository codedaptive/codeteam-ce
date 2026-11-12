#!/bin/bash
# Work-order trees belong to their lane, but remain subject to zone walls, including
# after a tree is removed. Standing and shared-store trees keep their behavior.
# The throwaway team is inside CODETEAM_WORKSPACE so the guard applies. No sleeps.
for v in $(compgen -e); do
    case "$v" in CODETEAM_*|CT_*|GIT_*|PYTHONPATH|PYTHONHOME) unset "$v" ;; esac
done
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null
set -e
root="$(cd "$(dirname "$0")/../.." && pwd)"
G="$root/share/claude-hooks/zone-guard.py"
T="$root/scratchpad/zone-guard-wo-trees-$$"
mkdir "$T"
trap 'rm -rf "$T"' EXIT
export GIT_CEILING_DIRECTORIES="$T"
W="$T/team-x/workcrews/AKit/repo-AKit"
A="$T/team-x/wo/AKit/wo1"
B="$T/team-x/wo/BKit/wo1"
S="$T/team-x/shared/.claude/worktrees/one"
mkdir -p "$T/team-x/team"
printf '%s\n' '{"lanes": {"AKit": {"path": "packages/kits/AKit"}, "BKit": {"path": "packages/kits/BKit"}}}' > "$T/team-x/team/team.json"
for repo in "$W" "$A" "$B" "$S"; do
    mkdir -p "$repo/packages/kits/AKit" "$repo/packages/kits/BKit"
    echo x > "$repo/packages/kits/AKit/x"
    echo x > "$repo/packages/kits/BKit/x"
    git -C "$repo" init -q
    git -C "$repo" add packages/kits/AKit/x packages/kits/BKit/x
done
export CODETEAM_ZONE=packages/kits/AKit CODETEAM_SESSION=AKit CODETEAM_SWT="$W" CODETEAM_WORKSPACE="$T"
PASS=0; FAIL=0
failures=()
expect() {
    local wanted="$1" tool="$2" input="$3" cwd="$4" name="$5" got
    if printf '{"tool_name":"%s","tool_input":%s,"cwd":"%s"}\n' "$tool" "$input" "$cwd" | python3 "$G" pretool >/dev/null 2>&1; then
        got=0
    else
        got=$?
    fi
    if [ "$got" = "$wanted" ]; then
        PASS=$((PASS+1)); echo "  PASS $name"
    else
        FAIL=$((FAIL+1)); failures+=("  FAIL $name (exit $got, wanted $wanted)")
        echo "${failures[${#failures[@]}-1]}"
    fi
}
expect 0 Edit "{\"file_path\":\"$A/packages/kits/AKit/x\"}" "$W" "own wo zone edit"
expect 0 Bash "{\"command\":\"echo y > $A/packages/kits/AKit/x\"}" "$W" "own wo zone shell write"
expect 0 Bash '{"command":"swift build"}' "$A/packages/kits/AKit" "own wo zone swift build"
expect 2 Edit "{\"file_path\":\"$A/packages/kits/BKit/x\"}" "$W" "own wo other zone edit"
expect 2 Edit "{\"file_path\":\"$B/packages/kits/AKit/x\"}" "$W" "other lane wo edit"
expect 2 Edit "{\"file_path\":\"$T/team-x/wo/AKitX/wo1/packages/kits/AKit/x\"}" "$W" "lookalike lane wo edit"
expect 2 Edit "{\"file_path\":\"$T/team-x/wo/AKit/notes.txt\"}" "$W" "lane wo parent file edit"
expect 2 Edit "{\"file_path\":\"$T/team-x/wo/AKit/gone/packages/kits/BKit/x\"}" "$W" "missing own wo other zone edit"
expect 0 Edit "{\"file_path\":\"$T/team-x/wo/AKit/gone/packages/kits/AKit/x\"}" "$W" "missing own wo zone edit"
expect 0 Edit "{\"file_path\":\"$W/packages/kits/AKit/x\"}" "$W" "standing zone edit"
expect 2 Edit "{\"file_path\":\"$W/packages/kits/BKit/x\"}" "$W" "standing other zone edit"
expect 0 Edit "{\"file_path\":\"$S/packages/kits/AKit/x\"}" "$W" "shared store zone edit"
echo "  $PASS passed, $FAIL failed"
if [ "$FAIL" -ne 0 ]; then
    printf 'Failing cases:\n' >&2
    printf '%s\n' "${failures[@]}" >&2
    exit 1
fi
