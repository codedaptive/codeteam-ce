#!/bin/bash
# zone/tests/zone-guard-scratch.sh: everything under a lane's own scratchpad/ and
# ledger/ is the lane's own, even inside a git clone kept there: the scratch
# carve-out takes precedence over worktree detection.
# Runs zone-guard.py's pretool mode on a throwaway team folder inside CODETEAM_WORKSPACE,
# so the guard applies; the folder is removed on exit.
# slow: about 6.5 s; each of the 28 checks starts a fresh python3 for the guard,
# which runs git itself, and setup git-inits and commits four repositories. No sleeps.
# Keep HOME real: its ~/.claude/audit append is intentional. CODETEAM_WORKSPACE is the throwaway folder.
# No inherited session or Git/Python setting may aim the guard at the live team.
for v in $(compgen -e); do case "$v" in CODETEAM_*|CT_*|GIT_*) unset "$v";; esac; done
unset PYTHONPATH PYTHONHOME
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null
root="$(cd "$(dirname "$0")/../.." && pwd)"
G="$root/share/claude-hooks/zone-guard.py"
T="$root/scratchpad/zone-guard-scratch-test-$$"
trap 'rm -rf "$T"' EXIT
rm -rf "$T"
L="$T/team-x/workcrews/AKit"; W="$L/repo-AKit"; O="$T/team-x/workcrews/BKit"
mkdir -p "$T/team-x/team" "$W/packages/kits/AKit" "$O/scratchpad" "$T/ct-home"
export CODETEAM_HOME="$T/ct-home" CODETEAM_BIN=/usr/bin/false CODETEAM_WORKSPACE="$T"
export GIT_CEILING_DIRECTORIES="$T"
git -C "$W" init -q
# A tracked file at the repo top, outside the zone (untracked top files are the lane's own).
echo x > "$W/README"; git -C "$W" add -A; git -C "$W" -c user.email=t@t -c user.name=t commit -qm init
[ -n "$(git -C "$W" ls-files README)" ] || { echo "  FAIL setup: lane repo not created"; exit 1; }
echo '{"lanes": {"AKit": {"path": "packages/kits/AKit"}, "BKit": {"path": "packages/kits/BKit"}}}' > "$T/team-x/team/team.json"
# A clone with a tracked file in the lane's scratchpad and ledger, and one in another lane's scratchpad.
for c in "$L/scratchpad/pf-clone" "$L/ledger/replay/clone" "$O/scratchpad/pf-clone"; do
    mkdir -p "$c/src"; echo x > "$c/src/a.py"; git -C "$c" init -q
    git -C "$c" add -A; git -C "$c" -c user.email=t@t -c user.name=t commit -qm init
    [ -n "$(git -C "$c" ls-files src/a.py)" ] || { echo "  FAIL setup: clone $c not created"; exit 1; }
done
# A symlink in the lane's scratchpad to the lane repo's top, outside the zone.
ln -s "$W" "$L/scratchpad/link"
export CODETEAM_ZONE=packages/kits/AKit CODETEAM_SESSION=AKit CODETEAM_SWT="$W"
PASS=0; FAIL=0
run() { echo "{\"tool_name\":\"$1\",\"tool_input\":$2,\"cwd\":\"$W\"}" | python3 "$G" pretool >/dev/null 2>&1; echo $?; }
expect() { got=$(run "$2" "$3"); if [ "$got" = "$1" ]; then PASS=$((PASS+1)); echo "  PASS $4"; else FAIL=$((FAIL+1)); echo "  FAIL $4 (exit $got, wanted $1)"; fi; }
expect 0 Edit "{\"file_path\":\"$L/scratchpad/pf-clone/src/a.py\"}" "an edit in a clone in the lane's scratchpad is allowed"
expect 0 Bash "{\"command\":\"rm -rf $L/scratchpad/pf-clone\"}" "rm of a clone in the lane's scratchpad is allowed"
expect 0 Bash "{\"command\":\"echo y > $L/scratchpad/pf-clone/src/a.py\"}" "a shell write in a scratchpad clone is allowed"
expect 0 Edit "{\"file_path\":\"$L/ledger/replay/clone/src/a.py\"}" "an edit in a clone in the lane's ledger is allowed"
expect 2 Edit "{\"file_path\":\"$O/scratchpad/pf-clone/src/a.py\"}" "a clone in another lane's scratchpad stays outside"
expect 2 Edit "{\"file_path\":\"$L/scratchpad/link/README\"}" "a symlink in the scratchpad does not make its target own"
cwdrun() { echo "{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"xcodebuild\"},\"cwd\":\"$L/scratchpad/link\"}" | python3 "$G" pretool >/dev/null 2>&1; echo $?; }
got=$(cwdrun); if [ "$got" = 2 ]; then PASS=$((PASS+1)); echo "  PASS a build from a scratchpad symlink to the repo is refused"; else FAIL=$((FAIL+1)); echo "  FAIL a build from a scratchpad symlink to the repo is refused (exit $got, wanted 2)"; fi
# No git commit or push from a repository under the lane's scratchpad/ or ledger/,
# however git reaches it; everything else there stays own.
C="$L/scratchpad/pf-clone2"; cp -R "$L/scratchpad/pf-clone" "$C"
runin() { echo "{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"$2\"},\"cwd\":\"$1\"}" | python3 "$G" pretool >/dev/null 2>&1; echo $?; }
expectin() { got=$(runin "$2" "$3"); if [ "$got" = "$1" ]; then PASS=$((PASS+1)); echo "  PASS $4"; else FAIL=$((FAIL+1)); echo "  FAIL $4 (exit $got, wanted $1)"; fi; }
expectin 2 "$W" "git -C $C commit -qam x" "git -C <scratchpad clone> commit is refused"
expectin 2 "$W" "git -C $C push origin main" "git -C <scratchpad clone> push is refused"
expectin 2 "$C" "git commit -qam x" "git commit with the hook's cwd in a scratchpad clone is refused"
expectin 2 "$C/src" "git push" "git push from a folder inside a scratchpad clone is refused"
expectin 2 "$W" "cd $C && git commit -qam x" "cd into a scratchpad clone, then git commit, is refused"
expectin 2 "$W" "git --git-dir=$C/.git --work-tree=$C push" "git --git-dir=<scratchpad clone> push is refused"
expectin 2 "$W" "GIT_DIR=$C/.git git push" "GIT_DIR=<scratchpad clone> git push is refused"
expectin 2 "$W" "git -C $L/ledger/replay/clone push" "git push from a ledger clone is refused"
expectin 2 "$W" "git -c user.name=t -C $C commit -m x" "git -c ... -C <scratchpad clone> commit is refused"
expectin 2 "$W" "git -C $C -c alias.p=push p" "a -c alias for push in a scratchpad clone is refused"
git -C "$C" config alias.ci commit
expectin 2 "$C" "git ci -am x" "an alias for commit in the clone's config is refused"
expectin 2 "$C" "git config alias.p2 push" "setting an alias for push in a scratchpad clone is refused"
expectin 2 "$C" "git config alias.sh '!git push'" "setting a shell alias in a scratchpad clone is refused"
expectin 2 "$W" "git --attr-source HEAD -C $C push" "an option value read as the subcommand does not hide a push"
expectin 2 "$W" "env -C $C git push" "env -C <scratchpad clone> git push is refused"
expectin 2 "$W" "env -u FOO GIT_DIR=$C/.git git push" "env -u FOO does not hide GIT_DIR"
expectin 2 "$W" "env -S 'git -C $C push'" "env -S carrying a push is refused"
expectin 0 "$C" "git config alias.st status && git st" "a harmless alias in a scratchpad clone is allowed"
expectin 0 "$C" "git status && git add -A && git log -1" "other git commands in a scratchpad clone are allowed"
expectin 0 "$W" "git commit -qm x" "git commit in the lane's worktree is allowed"
expectin 0 "$W" "rm -rf $C" "rm of a scratchpad clone is still allowed"
echo "  $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
