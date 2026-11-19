#!/bin/bash
# The zone guard's pretool hook refuses the orchestrator (CODETEAM_SESSION orc, a manifest,
# no CODETEAM_SWT) a write in or on a code package folder (a folder below the repo root holding
# Cargo.toml, Package.swift or pyproject.toml), naming the lane that covers it or saying it has no
# lane, even where the manifest's orchestrator_owns lists the path. Refused: an edit, shell writes,
# git rm, mv, restore, checkout, stash push, clean and reset --hard. Allowed: root files (a
# root Cargo.toml too), docs, manifests, git add, commit, restore --staged, make and cargo;
# a lane session and a staff session are unaffected.
# The throwaway team (team-x: a repo with packages/widget under lane Widget and tools/stray under
# no lane, a copy as the lane's worktree, a team.json, and two manifests, one with
# orchestrator_owns) lives in scratchpad/zone-guard-orc-packages-$$ under a fake HOME, so nothing
# touches the real HOME; it is removed on exit. Each check runs zone-guard.py pretool in a fresh
# python3. No sleeps, no network.
root="$(cd "$(dirname "$0")/../.." && pwd)"
G="$root/share/claude-hooks/zone-guard.py"
T="$root/scratchpad/zone-guard-orc-packages-$$"
trap 'rm -rf "$T"' EXIT
for v in $(compgen -e); do case "$v" in CODETEAM_*|CT_*) unset "$v";; esac; done
TX="$T/home/codeteam-work/team-x"
R="$TX/design/repo"
W="$TX/workcrews/Widget/repo-Widget"
mkdir -p "$TX/team" "$R/packages/widget/src" "$R/tools/stray" "$R/docs" "$R/teams" "$T/home"
export HOME="$T/home" GIT_CEILING_DIRECTORIES="$T" PYTHONDONTWRITEBYTECODE=1
printf '%s\n' '{"lanes":{"Widget":{"path":"packages/widget"}}}' > "$TX/team/team.json"
printf '%s\n' '[package]' 'name = "widget"' 'version = "0.1.0"' > "$R/packages/widget/Cargo.toml"
printf '%s\n' '[project]' 'name = "stray"' > "$R/tools/stray/pyproject.toml"
printf '%s\n' '[workspace]' > "$R/Cargo.toml"
for file in README.md docs/x.md teams/x.toml packages/widget/src/lib.rs; do echo x > "$R/$file"; done
git -C "$R" init -q
git -C "$R" add -A
git -C "$R" -c user.email=t@t -c user.name=t commit -qm init || exit 1
mkdir -p "$W"
cp -R "$R/." "$W/"
printf 'product = "x"\nworktree_root = "%s"\nrepo = "%s"\n' "$TX" "$R" > "$T/team.toml"
printf 'product = "x"\nworktree_root = "%s"\nrepo = "%s"\norchestrator_owns = ["packages/widget"]\n' "$TX" "$R" > "$T/owned.toml"
export CODETEAM_HOME="$root" CODETEAM_BIN=/usr/bin/true CODETEAM_SESSION=orc CODETEAM_MANIFEST="$T/team.toml"
ERR="$T/stderr"
PASS=0
FAIL=0
run() { printf '{"tool_name":"%s","tool_input":%s,"cwd":"%s"}\n' "$1" "$2" "$3" | python3 "$G" pretool >/dev/null 2>"$ERR"; return $?; }
expect() {
  local wanted="$1" tool="$2" input="$3" cwd="$4" label="$5" text="${6:-}" text2="${7:-}" got
  run "$tool" "$input" "$cwd"; got=$?
  if [ "$got" = "$wanted" ] && { [ -z "$text" ] || grep -Fq "$text" "$ERR"; } && { [ -z "$text2" ] || grep -Fq "$text2" "$ERR"; }; then
    PASS=$((PASS+1)); echo "  PASS $label"
  else
    FAIL=$((FAIL+1)); echo "  FAIL $label (exit $got, wanted $wanted; stderr: $(head -c 200 "$ERR" | tr '\n' ' '))"
  fi
}
expect 2 Edit "{\"file_path\":\"$R/packages/widget/src/lib.rs\"}" "$R" 'orc edit lane package' Widget 'code package'
CODETEAM_MANIFEST="$T/owned.toml" expect 2 Edit "{\"file_path\":\"$R/packages/widget/src/lib.rs\"}" "$R" 'orc edit orchestrator-owned package' Widget 'code package'
for file in README.md docs/x.md teams/x.toml Cargo.toml; do
  expect 0 Edit "{\"file_path\":\"$R/$file\"}" "$R" "orc edit $file"
done
expect 2 Edit "{\"file_path\":\"$R/tools/stray/x.py\"}" "$R" 'orc edit uncovered package' 'has no lane'
for command in 'echo x > packages/widget/a.rs' 'rm -rf packages' 'cp README.md packages/widget/'; do
  expect 2 Bash "{\"command\":\"$command\"}" "$R" "orc shell $command"
done
expect 0 Bash '{"command":"echo x > docs/y.md"}' "$R" 'orc shell docs write'
for command in 'git rm packages/widget/Cargo.toml' 'git mv README.md packages/widget/R.md' 'git checkout -- packages/widget' 'git restore packages/widget/src/lib.rs' 'git restore -- --staged packages/widget/src/lib.rs' 'git stash push -- packages/widget' 'git clean -fd' 'git reset --hard'; do
  expect 2 Bash "{\"command\":\"$command\"}" "$R" "orc $command"
done
for command in 'git add packages/widget/src/lib.rs' 'git add .' 'git add docs/x.md' 'git add -A' 'git commit -m x' 'git restore --staged packages/widget/src/lib.rs' 'git rm docs/x.md' 'make build' 'cargo test'; do
  expect 0 Bash "{\"command\":\"$command\"}" "$R" "orc $command"
done
export CODETEAM_SESSION=Widget CODETEAM_ZONE=packages/widget CODETEAM_SWT="$W"
expect 0 Edit "{\"file_path\":\"$W/packages/widget/src/lib.rs\"}" "$W" 'lane edit own package'
expect 2 Edit "{\"file_path\":\"$W/README.md\"}" "$W" 'lane edit root file' 'outside zone'
unset CODETEAM_ZONE CODETEAM_SWT
export CODETEAM_SESSION=Kong
expect 0 Edit "{\"file_path\":\"$R/packages/widget/src/lib.rs\"}" "$R" 'staff edit package'
echo "== zone-guard-orc-packages: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
