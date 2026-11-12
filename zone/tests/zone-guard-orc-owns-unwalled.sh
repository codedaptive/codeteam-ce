#!/bin/bash
# zone/tests/zone-guard-orc-owns-unwalled.sh: the zone guard refuses an unwalled '.' lane's write to a path the
# manifest's top-level `orchestrator_owns` names (for the git
# rows). The lane is Widget, zone '.', and its team/team.json names only Widget, so no other lane has an area here:
# unwalled. zone-guard.py's main runs pretool for such a lane when the manifest's orchestrator_owns is non-empty.
# Refused (exit 2): an Edit to teams/x.toml; shell writes to it (echo >, tee, cp into the owned folder, rm); and
# git add, git rm and git mv of an owned path (teams/x.toml, teams, bin/foo to teams/y.toml, teams/x.toml to bin/z).
# The refusal's stderr names Orc-X and the orchestrator and not "outside zone". Allowed: an Edit to bin/foo and to
# docs/x.md; a shell write to bin/foo (echo > bin/foo); git add bin/foo, git restore and git checkout of an owned
# path, and git commit; and make test-one, cargo test and make build, which a zoned lane is refused. For this lane
# the guard checks writes to orchestrator_owns paths only: of git it checks the three staging subcommands (add, rm,
# mv), and no other subcommand. With a manifest without the key, the Edit to teams/x.toml and git rm teams/x.toml
# are allowed. A commit and an add from the lane's scratch clone (under its scratchpad) are allowed too: the scratch-clone rule (no
# commit or push from such a clone) is not applied to this lane; the same commit from a walled lane is refused (the
# last check, which rewrites team/team.json to name a second lane). Twenty-eight checks: twenty-five python3 runs of
# the worktree's zone-guard.py in pretool mode, each with its own JSON on stdin (the three stderr checks, 2, 8 and
# 28, read the stderr of the run before them, so they are not runs of their own). Nothing is executed: every command
# is only the JSON the guard reads. The throwaway folders are under scratchpad/ and removed on exit. HOME is a scratch
# folder too (the guard logs to $HOME/.claude/audit), and the lane's team folder sits under HOME/codeteam-work (the default workspace), as a lane
# does under the real HOME, so the guard classifies the lane's paths as in production: a tracked file by its rule,
# an untracked top-level entry as the lane's own, and the scratch clone as the lane's own. The lane's files are
# tracked, so no check depends on the untracked carve-out. No sleeps, no network: about a second. The guard runs by
# its own path (never $CODETEAM_HOME's copy).
root="$(cd "$(dirname "$0")/../.." && pwd)"
G="$root/share/claude-hooks/zone-guard.py"
T="$root/scratchpad/zone-guard-orc-owns-unwalled-test-$$"
trap 'rm -rf "$T"' EXIT
rm -rf "$T"
# Same result from a lane session as from a plain shell: clear every CODETEAM_* and CT_* the caller
# exported, then set the lane's own facts (zone-guard-orc-owns.sh does the same).
for v in $(compgen -e); do case "$v" in CODETEAM_*|CT_*) unset "$v";; esac; done
# The team folder team-x sits under the scratch HOME's codeteam-work (the default CODETEAM_WORKSPACE, which the guard guards).
# Widget, not a *Kit name: an AKit lane gives owns_doc the stem "A".
TX="$T/home/codeteam-work/team-x"
L="$TX/workcrews/Widget"; W="$L/repo-Widget"
mkdir -p "$TX/team" "$W/teams" "$W/bin" "$W/docs" "$T/home"
export GIT_CEILING_DIRECTORIES="$T"
git -C "$W" init -q
echo x > "$W/teams/x.toml"
echo x > "$W/bin/foo"
echo x > "$W/docs/x.md"
git -C "$W" add -A; git -C "$W" -c user.email=t@t -c user.name=t commit -qm init
git -C "$W" ls-files --error-unmatch teams/x.toml bin/foo docs/x.md >/dev/null 2>&1 \
  || { echo "  FAIL setup: lane repo not created"; exit 1; }
echo '{"lanes": {"Widget": {"path": "."}}}' > "$TX/team/team.json"
# A scratch clone in the lane's scratchpad, with a tracked teams/x.toml committed: the place the scratch-clone rule refuses commits
# and pushes from (a repository in the lane's scratchpad or ledger).
mkdir -p "$L/scratchpad/clone/teams"
git -C "$L/scratchpad/clone" init -q
echo x > "$L/scratchpad/clone/teams/x.toml"
git -C "$L/scratchpad/clone" add -A; git -C "$L/scratchpad/clone" -c user.email=t@t -c user.name=t commit -qm init
git -C "$L/scratchpad/clone" ls-files --error-unmatch teams/x.toml >/dev/null 2>&1 \
  || { echo "  FAIL setup: scratch clone not created"; exit 1; }
# The manifests: one with the key (top level, before the [[lanes]] table), one without it.
cat > "$T/orc.toml" <<'TOML'
product = "codeteam"
orchestrator_owns = ["teams"]

[[lanes]]
name = "Widget"
path = "."
TOML
cat > "$T/no-key.toml" <<'TOML'
product = "codeteam"

[[lanes]]
name = "Widget"
path = "."
TOML
export HOME="$T/home" CODETEAM_HOME="$root" CODETEAM_BIN=/usr/bin/true
export CODETEAM_ZONE=. CODETEAM_SESSION=Widget CODETEAM_SWT="$W"
export PYTHONDONTWRITEBYTECODE=1
ERR="$T/stderr.txt"
PASS=0; FAIL=0
# One pretool run of the guard: prints its exit code; its stderr is left in $ERR.
run() { echo "{\"tool_name\":\"$1\",\"tool_input\":$2,\"cwd\":\"$W\"}" | python3 "$G" pretool >/dev/null 2>"$ERR"; echo $?; }
expect() { got=$(run "$2" "$3"); if [ "$got" = "$1" ]; then PASS=$((PASS+1)); echo "  PASS $4"; else FAIL=$((FAIL+1)); echo "  FAIL $4 (exit $got, wanted $1)"; fi; }
# 1. Refused: an Edit to teams/x.toml, which orchestrator_owns names (the lane is unwalled, zone '.').
CODETEAM_MANIFEST="$T/orc.toml" expect 2 Edit "{\"file_path\":\"$W/teams/x.toml\"}" "unwalled: an edit to teams/x.toml, which orchestrator_owns names, is refused (exit 2)"
# 2. The refusal (check 1's run, its stderr) names the orchestrator Orc-X and is not the zoned "outside zone" text.
if grep -q "Orc-X" "$ERR" && grep -q "orchestrator" "$ERR" && ! grep -q "outside zone" "$ERR"; then
  PASS=$((PASS+1)); echo "  PASS unwalled: the refusal's stderr names Orc-X and the orchestrator, and not 'outside zone'"
else
  FAIL=$((FAIL+1)); echo "  FAIL unwalled: the refusal's stderr names Orc-X and the orchestrator, and not 'outside zone' (stderr: $(head -c 200 "$ERR" | tr '\n' ' '))"
fi
# 3. Refused: a shell write to the same path, a redirect.
CODETEAM_MANIFEST="$T/orc.toml" expect 2 Bash '{"command":"echo x > teams/x.toml"}' "unwalled: a shell write, echo x > teams/x.toml, is refused (exit 2)"
# 4. Refused: a shell write by rm, a write-command branch of the guard.
CODETEAM_MANIFEST="$T/orc.toml" expect 2 Bash '{"command":"rm teams/x.toml"}' "unwalled: rm teams/x.toml is refused (exit 2)"
# 5. Refused: a copy into the owned folder, the cp branch (its destination is teams/).
CODETEAM_MANIFEST="$T/orc.toml" expect 2 Bash '{"command":"cp bin/foo teams/"}' "unwalled: cp bin/foo teams/ (a copy into the owned folder) is refused (exit 2)"
# 6. Refused: a pipe into tee, the tee branch.
CODETEAM_MANIFEST="$T/orc.toml" expect 2 Bash '{"command":"echo x | tee teams/x.toml"}' "unwalled: echo x | tee teams/x.toml is refused (exit 2)"
# 7. Refused: git add of an owned file, the staging branch of git.
CODETEAM_MANIFEST="$T/orc.toml" expect 2 Bash '{"command":"git add teams/x.toml"}' "unwalled: git add teams/x.toml, an orchestrator_owns path, is refused (exit 2)"
# 8. The git refusal (check 7's run, its stderr) names Orc-X and the orchestrator and not "outside zone".
if grep -q "Orc-X" "$ERR" && grep -q "orchestrator" "$ERR" && ! grep -q "outside zone" "$ERR"; then
  PASS=$((PASS+1)); echo "  PASS unwalled: the git refusal's stderr names Orc-X and the orchestrator, and not 'outside zone'"
else
  FAIL=$((FAIL+1)); echo "  FAIL unwalled: the git refusal's stderr names Orc-X and the orchestrator, and not 'outside zone' (stderr: $(head -c 200 "$ERR" | tr '\n' ' '))"
fi
# 9. Refused: git add of the owned folder itself.
CODETEAM_MANIFEST="$T/orc.toml" expect 2 Bash '{"command":"git add teams"}' "unwalled: git add teams (the owned folder) is refused (exit 2)"
# 10. Refused: git rm of an owned file.
CODETEAM_MANIFEST="$T/orc.toml" expect 2 Bash '{"command":"git rm teams/x.toml"}' "unwalled: git rm teams/x.toml, an orchestrator_owns path, is refused (exit 2)"
# 11. Refused: git mv into the owned folder (the destination is owned).
CODETEAM_MANIFEST="$T/orc.toml" expect 2 Bash '{"command":"git mv bin/foo teams/y.toml"}' "unwalled: git mv bin/foo teams/y.toml (the destination is owned) is refused (exit 2)"
# 12. Refused: git mv out of the owned folder (the source is owned).
CODETEAM_MANIFEST="$T/orc.toml" expect 2 Bash '{"command":"git mv teams/x.toml bin/z"}' "unwalled: git mv teams/x.toml bin/z (the source is owned) is refused (exit 2)"
# 13-14. Controls: an edit to any other path is allowed for an unwalled lane.
CODETEAM_MANIFEST="$T/orc.toml" expect 0 Edit "{\"file_path\":\"$W/bin/foo\"}" "unwalled control: an edit to bin/foo, not orchestrator_owns, is allowed (exit 0)"
CODETEAM_MANIFEST="$T/orc.toml" expect 0 Edit "{\"file_path\":\"$W/docs/x.md\"}" "unwalled control: an edit to docs/x.md, not orchestrator_owns, is allowed (exit 0)"
# 15. Control: a shell write to a path not orchestrator_owns is allowed.
CODETEAM_MANIFEST="$T/orc.toml" expect 0 Bash '{"command":"echo x > bin/foo"}' "unwalled control: echo x > bin/foo, a shell write to a path not orchestrator_owns, is allowed (exit 0)"
# 16. Control: git add of a path not orchestrator_owns is allowed.
CODETEAM_MANIFEST="$T/orc.toml" expect 0 Bash '{"command":"git add bin/foo"}' "unwalled control: git add bin/foo, a path not orchestrator_owns, is allowed (exit 0)"
# 17-18. Controls: git restore and git checkout of an owned path are not refused for this lane.
CODETEAM_MANIFEST="$T/orc.toml" expect 0 Bash '{"command":"git restore teams/x.toml"}' "unwalled control: git restore teams/x.toml is allowed (exit 0)"
CODETEAM_MANIFEST="$T/orc.toml" expect 0 Bash '{"command":"git checkout -- teams/x.toml"}' "unwalled control: git checkout -- teams/x.toml is allowed (exit 0)"
# 19. Control: git commit is not checked for this lane.
CODETEAM_MANIFEST="$T/orc.toml" expect 0 Bash '{"command":"git commit -m x"}' "unwalled control: git commit -m x is allowed (exit 0)"
# 20-22. Controls: the make and build commands a zoned lane is refused are allowed for an unwalled lane.
CODETEAM_MANIFEST="$T/orc.toml" expect 0 Bash '{"command":"make test-one DIR=bin"}' "unwalled control: make test-one DIR=bin is allowed (exit 0)"
CODETEAM_MANIFEST="$T/orc.toml" expect 0 Bash '{"command":"cargo test"}' "unwalled control: cargo test is allowed (exit 0)"
CODETEAM_MANIFEST="$T/orc.toml" expect 0 Bash '{"command":"make build"}' "unwalled control: make build is allowed (exit 0)"
# 23. Control: the same Edit to teams/x.toml is allowed with a manifest that has no orchestrator_owns.
CODETEAM_MANIFEST="$T/no-key.toml" expect 0 Edit "{\"file_path\":\"$W/teams/x.toml\"}" "unwalled control: the edit to teams/x.toml is allowed with a manifest that has no orchestrator_owns (exit 0)"
# 24. Control: the same git rm of teams/x.toml is allowed with a manifest that has no orchestrator_owns.
CODETEAM_MANIFEST="$T/no-key.toml" expect 0 Bash '{"command":"git rm teams/x.toml"}' "unwalled control: git rm teams/x.toml is allowed with a manifest that has no orchestrator_owns (exit 0)"
# 25. Control: a commit from the lane's scratch clone is allowed. the scratch-clone rule (no commit or push from a repository in the
# lane's scratchpad or ledger) is not applied to an unwalled lane, so the guard does not refuse it.
CODETEAM_MANIFEST="$T/orc.toml" expect 0 Bash "{\"command\":\"git -C $L/scratchpad/clone commit -m x\"}" "unwalled control: git -C <scratch clone> commit -m x is allowed (exit 0): the scratch-clone rule is off for this lane"
# 26. Control: an add of a tracked file in the scratch clone is allowed (the scratch clone classifies as the lane's own).
CODETEAM_MANIFEST="$T/orc.toml" expect 0 Bash "{\"command\":\"git -C $L/scratchpad/clone add teams/x.toml\"}" "unwalled control: git -C <scratch clone> add teams/x.toml is allowed (exit 0)"
# 27. Contrast: the same commit from a scratch clone is refused for a walled lane (the scratch-clone rule). Rewritten here, last: the
# team.json names a second lane, so Widget is walled; no row after this one reads the unwalled team.json.
echo '{"lanes": {"Widget": {"path": "."}, "Other": {"path": "other"}}}' > "$TX/team/team.json"
CODETEAM_MANIFEST="$T/orc.toml" expect 2 Bash "{\"command\":\"git -C $L/scratchpad/clone commit -m x\"}" "walled contrast: the same git -C <scratch clone> commit -m x is refused (exit 2) for a walled lane"
# 28. The walled refusal (check 27's run, its stderr) is the scratch-clone rule's.
if grep -q "no commit or push from there\|work reaches exchange only from" "$ERR"; then
  PASS=$((PASS+1)); echo "  PASS walled contrast: the refusal is the scratch-clone rule's"
else
  FAIL=$((FAIL+1)); echo "  FAIL walled contrast: the refusal is the scratch-clone rule's (stderr: $(head -c 200 "$ERR" | tr '\n' ' '))"
fi
echo "== zone-guard-orc-owns-unwalled: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
