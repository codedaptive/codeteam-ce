#!/bin/bash
# Each hook process uses the current lane owns, with the environment as fallback.
root="$(cd "$(dirname "$0")/../.." && pwd)"
G="$root/share/claude-hooks/zone-guard.py"
for v in $(compgen -e); do case "$v" in CODETEAM_*|CT_*) unset "$v";; esac; done
T=$(mktemp -d "$root/scratchpad/zone-guard-live-walls.XXXXXXXX") || exit 1
trap 'rm -rf "$T"' EXIT
W="$T/team-x/workcrews/AKit/repo-AKit"
TEAM="$T/team-x/team/team.json"
mkdir -p "$T/team-x/team" "$W/packages/kits/AKit" "$W/packages/kits/BKit" \
  "$W/packages/libs/Old" "$W/packages/libs/New" "$W/packages/libs/Newer" || exit 1
export GIT_CEILING_DIRECTORIES="$T"
git -C "$W" init -q || exit 1
for f in packages/kits/AKit/x.swift packages/kits/BKit/x.swift \
  packages/libs/Old/x.swift packages/libs/New/x.swift packages/libs/Newer/x.swift; do
  echo x > "$W/$f"
done
git -C "$W" add -A || exit 1
git -C "$W" -c user.email=t@t -c user.name=t commit -qm init || exit 1
export CODETEAM_SWT="$W" CODETEAM_HOME="$root" CODETEAM_MANIFEST="$T/no-manifest.toml"
export CODETEAM_ZONE=packages/kits/AKit CODETEAM_SESSION=AKit CODETEAM_OWNS=packages/libs/Old
export PYTHONDONTWRITEBYTECODE=1
PASS=0; FAIL=0
run() { echo "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$W/$1\"},\"cwd\":\"$W\"}" | python3 "$G" pretool >/dev/null 2>&1; echo $?; }
expect() { got=$(run "$2"); if [ "$got" = "$1" ]; then PASS=$((PASS+1)); echo "  PASS $3"; else FAIL=$((FAIL+1)); echo "  FAIL $3 (exit $got, wanted $1)"; fi; }

cat > "$TEAM" <<'JSON'
{"lanes":{"AKit":{"path":"packages/kits/AKit","owns":["packages/libs/New"]},"BKit":{"path":"packages/kits/BKit"}}}
JSON
expect 0 packages/libs/New/x.swift "team.json New allowed"
expect 2 packages/libs/Old/x.swift "team.json overrides environment Old"

cat > "$TEAM" <<'JSON'
{"lanes":{"AKit":{"path":"packages/kits/AKit","owns":["packages/libs/Newer"]},"BKit":{"path":"packages/kits/BKit"}}}
JSON
expect 0 packages/libs/Newer/x.swift "updated Newer allowed without restart"
expect 2 packages/libs/New/x.swift "updated walls refuse New without restart"
brief=$(echo '{}' | python3 "$G" start 2>/dev/null)
if [[ "$brief" == *'packages/libs/Newer'* ]]; then PASS=$((PASS+1)); echo "  PASS start brief names Newer"; else FAIL=$((FAIL+1)); echo "  FAIL start brief names Newer"; fi
if [[ "$brief" != *'packages/libs/Old'* ]]; then PASS=$((PASS+1)); echo "  PASS start brief omits Old"; else FAIL=$((FAIL+1)); echo "  FAIL start brief omits Old"; fi

cat > "$TEAM" <<'JSON'
{"lanes":{"AKit":{"path":"packages/kits/AKit"},"BKit":{"path":"packages/kits/BKit"}}}
JSON
expect 0 packages/libs/Old/x.swift "missing owns falls back to Old"
cat > "$TEAM" <<'JSON'
{"lanes":{"BKit":{"path":"packages/kits/BKit"}}}
JSON
expect 0 packages/libs/Old/x.swift "missing AKit falls back to Old"
echo '{not json' > "$TEAM"
expect 0 packages/libs/Old/x.swift "invalid JSON falls back to Old"
expect 0 packages/kits/AKit/x.swift "invalid JSON still allows own zone"
expect 2 packages/kits/BKit/x.swift "invalid JSON still refuses BKit"
cat > "$TEAM" <<'JSON'
{"lanes":{"AKit":{"path":"packages/kits/AKit","owns":[]},"BKit":{"path":"packages/kits/BKit"}}}
JSON
expect 2 packages/libs/Old/x.swift "empty owns refuses Old"
echo "== zone-guard-live-walls: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
