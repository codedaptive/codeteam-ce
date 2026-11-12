#!/bin/bash
# zone-guard.py self-test on a throwaway team folder (inside CODETEAM_WORKSPACE, so it is guarded).
G="$(cd "$(dirname "$0")/.." && pwd)/share/claude-hooks/zone-guard.py"
# One folder per run ($$): two runs at once shared one folder, and when one removed it the other's
# `git -C $W commit` found the codeteam repo above and committed into it (2026-10-24).
T="$(cd "$(dirname "$0")/.." && pwd)/scratchpad/zone-guard-test-$$"
trap 'rm -rf "$T"' EXIT
rm -rf "$T"; mkdir -p "$T/team-x/team" "$T/team-x/workcrews/AKit"
W="$T/team-x/workcrews/AKit/repo-AKit"
mkdir -p "$W/packages/kits/AKit/Sources" "$W/packages/kits/BKit/Sources" "$W/docs/reference" "$W/apps/acme"
touch "$W/docs/reference/AKIT_SPEC.md" "$W/docs/reference/BKIT_SPEC.md" "$W/packages/kits/AKit/Sources/x.swift" "$W/packages/kits/BKit/Sources/x.swift"
git -C "$W" init -q
# git never looks above the test repo, so a missing $W fails instead of finding the codeteam repo
export GIT_CEILING_DIRECTORIES="$(dirname "$W")"
[ -d "$W/.git" ] || { echo "  FAIL test repo not created"; exit 1; }
git -C "$W" add -A && git -C "$W" -c user.email=t@t -c user.name=t commit -qm init
echo '{"lanes": {"AKit": {"path": "packages/kits/AKit"}, "BKit": {"path": "packages/kits/BKit"}}}' > "$T/team-x/team/team.json"
# Same result from a lane session as from a plain shell: clear every CODETEAM_* and CT_* the caller
# exported (besides the three set below, the guard reads CODETEAM_OWNS, _HOME, _BIN, _MANIFEST, _CTX_WINDOW and CT_CTX_PREPARE; a
# lane's CODETEAM_OWNS let "another zone's SPEC" through, and its _BIN/_MANIFEST aim post() at the live team).
for v in $(compgen -e); do case "$v" in CODETEAM_*|CT_*) unset "$v";; esac; done
export CODETEAM_WORKSPACE="$T"   # the throwaway team folder is in the workspace, so the guard applies
export CODETEAM_ZONE=packages/kits/AKit CODETEAM_SESSION=AKit CODETEAM_SWT="$W"
PASS=0; FAIL=0
run() { echo "{\"tool_name\":\"$1\",\"tool_input\":$2,\"cwd\":\"$W\"}" | python3 "$G" pretool >/dev/null 2>&1; echo $?; }
expect() { got=$(run "$2" "$3"); if [ "$got" = "$1" ]; then PASS=$((PASS+1)); echo "  PASS $4"; else FAIL=$((FAIL+1)); echo "  FAIL $4 (exit $got, wanted $1)"; fi; }
expect 2 Bash '{"command":"make test-one DIR=packages/kits/BKit/rust"}' "another zone's tests are refused"
expect 2 Bash '{"command":"make test-one DIR=packages/kits/AKit/rust CARGO_TEST_ARGS=\"--test x\""}' "make test-one on the zone is refused: zone-test-one is the one route (2026-11-01)"
expect 0 Bash '{"command":"make zone-test-one DIR=packages/kits/AKit/rust"}' "make zone-test-one on the zone runs"
expect 2 Bash '{"command":"cargo test --manifest-path packages/kits/AKit/rust/Cargo.toml"}' "cargo test on the zone is refused"
expect 2 Bash '{"command":"cd packages/kits/AKit && swift test --filter x"}' "swift test on the zone is refused"
expect 2 Bash '{"command":"xcodebuild test -scheme AKit"}' "xcodebuild test is refused"
expect 2 Bash '{"command":"make test-repeat DIR=packages/kits/AKit"}' "make test-repeat is refused"
expect 2 Bash '{"command":"caffeinate -i make test-one DIR=packages/kits/AKit"}' "a wrapped make test-one is refused"
expect 2 Bash '{"command":"bash -c \"cargo test\""}' "cargo test inside bash -c is refused"
expect 0 Bash '{"command":"cd packages/kits/AKit && swift build"}' "swift build on the zone runs"
expect 0 Bash '{"command":"make -n test-one DIR=packages/kits/AKit"}' "make -n test-one runs nothing and is allowed"
expect 0 Bash '{"command":"make zone-test-status"}' "make zone-test-status runs"
expect 0 Bash '{"command":"make zone-test 2>&1 | tail -5"}' "make zone-test runs"
expect 2 Bash '{"command":"python3 scripts/test-times.py packages/kits/BKit/rust"}' "test-times.py on another zone is refused"
expect 2 Bash '{"command":"python3 ~/codeteam/bin/swift-test-xcode packages/kits/BKit --filter x"}' "codeteam's swift-test-xcode on another zone is refused"
expect 2 Bash '{"command":"python3 ~/codeteam/bin/swift-test-xcode packages/kits/AKit --filter x"}' "codeteam's swift-test-xcode on the zone is refused (no record)"
runa() { echo "{\"tool_name\":\"$1\",\"tool_input\":$2,\"cwd\":\"$W\",\"agent_id\":\"a1\"}" | python3 "$G" pretool >/dev/null 2>&1; echo $?; }
expecta() { got=$(runa "$2" "$3"); if [ "$got" = "$1" ]; then PASS=$((PASS+1)); echo "  PASS $4"; else FAIL=$((FAIL+1)); echo "  FAIL $4 (exit $got, wanted $1)"; fi; }
got=$(runa Bash '{"command":"make zone-test"}'); if [ "$got" = 2 ]; then PASS=$((PASS+1)); echo "  PASS a subagent's make zone-test is refused"; else FAIL=$((FAIL+1)); echo "  FAIL a subagent's make zone-test is refused (exit $got)"; fi
got=$(runa Bash '{"command":"make zone-test-one DIR=packages/kits/AKit"}'); if [ "$got" = 0 ]; then PASS=$((PASS+1)); echo "  PASS a subagent's make zone-test-one runs"; else FAIL=$((FAIL+1)); echo "  FAIL a subagent's make zone-test-one runs (exit $got)"; fi
# The build-queue verbs: a subagent waits on and submits its own jobs.
expect 0 Bash '{"command":"make zone-test-one DIR=packages/kits/AKit CLASS=post"}' "make zone-test-one with CLASS=post on the zone runs"
expecta 0 Bash '{"command":"zone-tool job wait 20990101-000000-abcdef"}' "a subagent's zone-tool job wait runs"
expecta 0 Bash '{"command":"zone-tool job submit --class dev -- true"}' "a subagent's zone-tool job submit runs"
expect 2 Bash '{"command":"make zone-test ZONE=packages/kits/BKit"}' "zone-test pointed at another zone is refused"
expect 2 Bash '{"command":"make build"}' "a whole-product target is refused"
expect 2 Bash '{"command":"caffeinate -i make test-changed BASE=abc"}' "a wrapped whole-product target is refused"
expect 0 Bash '{"command":"command -v make rg"}' "command -v is not a make run"
expect 2 Edit "{\"file_path\":\"$W/packages/kits/BKit/Sources/x.swift\"}" "an edit in another zone is refused"
expect 0 Edit "{\"file_path\":\"$W/packages/kits/AKit/Sources/x.swift\"}" "an edit in the zone is allowed"
expect 0 Edit "{\"file_path\":\"$W/docs/reference/AKIT_SPEC.md\"}" "the zone's own SPEC is the zone's"
expect 2 Edit "{\"file_path\":\"$W/docs/reference/BKIT_SPEC.md\"}" "another zone's SPEC is refused"
expect 2 Bash '{"command":"cd packages/kits/BKit && sed -i \"\" s/a/b/ Sources/x.swift"}' "sed -i in another zone is refused"
expect 2 Bash '{"command":"echo x >> packages/kits/BKit/notes.md"}' "a shell write into another zone is refused"
expect 0 Bash '{"command":"git status --short && rg foo packages/kits/BKit"}' "reading another zone is allowed"
expect 0 Bash '{"command":"git restore packages/kits/BKit/Sources/x.swift"}' "undoing a stray edit is allowed"
expect 0 Bash '{"command":"(make warm > /tmp/w.log 2>&1 &) ; echo started"}' "a backgrounded make warm runs"
expect 0 Edit '{"file_path":"/tmp/scratch.txt"}' "files outside the repos are not guarded"
expect 0 Bash "{\"command\":\"echo note > $W/status.md\"}" "an untracked note at the worktree top is the lane's own"
# The startup notice names the SPEC/INTERFACE exception the guard allows (ZB1, 2026-10-24)
N=$(echo '{}' | python3 "$G" subagent 2>/dev/null)
if echo "$N" | grep -q "your zone's own SPEC and INTERFACE in \`docs/reference\` or \`docs/internal/reference\` and their \`docs/_public\` copies"; then PASS=$((PASS+1)); echo "  PASS the subagent notice names the SPEC and INTERFACE exception"; else FAIL=$((FAIL+1)); echo "  FAIL the subagent notice names the SPEC and INTERFACE exception"; fi
CODETEAM_ZONE=. expect 0 Bash '{"command":"make build"}' "the tooling lane (zone .) is not guarded"
# A whole-repo lane beside zone lanes (say, benchmarking beside the zones): it runs anything,
# and edits anything but another lane's folders.
mkdir -p "$W/tools" "$W/docs"; touch "$W/README" "$W/docs/AKIT_GUIDE.md" "$W/tools/a.sh" "$W/tools/b.sh"
git -C "$W" add -A >/dev/null 2>&1 && git -C "$W" -c user.email=t@t -c user.name=t commit -qm more >/dev/null 2>&1
CODETEAM_ZONE=. CODETEAM_SESSION=gauges expect 2 Edit "{\"file_path\":\"$W/packages/kits/AKit/Sources/x.swift\"}" "a whole-repo lane cannot edit a zone lane's folder"
CODETEAM_ZONE=. CODETEAM_SESSION=gauges expect 0 Edit "{\"file_path\":\"$W/README\"}" "a whole-repo lane edits what no lane owns"
CODETEAM_ZONE=. CODETEAM_SESSION=gauges expect 0 Bash '{"command":"make test-one DIR=packages/kits/BKit/rust"}' "a whole-repo lane runs and builds anything"
CODETEAM_ZONE=. CODETEAM_SESSION=gauges expect 2 Bash '{"command":"echo x > packages/kits/BKit/notes.md"}' "a whole-repo lane's shell write into a zone is refused"
# A zone lane's extra owned paths (the manifest's owns; globs allowed).
CODETEAM_OWNS="docs/AKIT_*.md:tools/a.sh" expect 0 Edit "{\"file_path\":\"$W/docs/AKIT_GUIDE.md\"}" "a zone lane edits a file its owns names"
CODETEAM_OWNS="docs/AKIT_*.md:tools/a.sh" expect 0 Bash '{"command":"echo x >> tools/a.sh"}' "a zone lane writes an owned file outside its folder"
CODETEAM_OWNS="docs/AKIT_*.md:tools/a.sh" expect 2 Edit "{\"file_path\":\"$W/tools/b.sh\"}" "a file its owns does not name stays refused"
# Context: at 75% of the window the session is told to write its handoff, once.
TR="$T/t.jsonl"
echo '{"type":"assistant","message":{"usage":{"input_tokens":10,"cache_read_input_tokens":149990,"output_tokens":0}}}' > "$TR"
ctx() { echo "{\"session_id\":\"s1\",\"transcript_path\":\"$TR\"}" | CODETEAM_CTX_WINDOW=200000 python3 "$G" context; }
C1=$(ctx); C2=$(ctx)
check() { if eval "$2"; then PASS=$((PASS+1)); echo "  PASS $1"; else FAIL=$((FAIL+1)); echo "  FAIL $1"; fi; }
check "at 75% the session is told to run prepare-for-compact" "echo \"\$C1\" | grep -q 'prepare-for-compact.md'"
check "it is told once, not on every tool call" "[ -z \"\$C2\" ]"
# Stop: with CODETEAM_NOTE_TOOLS set, a push with no note after it sends the session back once; unset, no check.
printf '%s\n' '{"type":"user","message":{"content":"go"}}' \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"git push origin lane/AKit"}}]}}' > "$T/s.jsonl"
S1=$(echo "{\"transcript_path\":\"$T/s.jsonl\"}" | CODETEAM_NOTE_TOOLS=file_note python3 "$G" stop)
S2=$(echo "{\"transcript_path\":\"$T/s.jsonl\",\"stop_hook_active\":true}" | CODETEAM_NOTE_TOOLS=file_note python3 "$G" stop)
S0=$(echo "{\"transcript_path\":\"$T/s.jsonl\"}" | python3 "$G" stop)
check "a push with no note is sent back to file one" "echo \"\$S1\" | grep -q '\"decision\": \"block\"'"
check "with no CODETEAM_NOTE_TOOLS there is no note check" "[ -z \"\$S0\" ]"
check "and only once" "[ -z \"\$S2\" ]"
# A whole-repo lane (zone "."): no fence, but the compaction prompt still comes.
echo '{"type":"assistant","message":{"usage":{"input_tokens":10,"cache_read_input_tokens":149990,"output_tokens":0}}}' > "$T/t2.jsonl"
rm -f "$T/team-x/workcrews/AKit/ledger/ctx-state.json"
C3=$(echo "{\"session_id\":\"s9\",\"transcript_path\":\"$T/t2.jsonl\"}" | CODETEAM_ZONE=. CODETEAM_CTX_WINDOW=200000 python3 "$G" context)
check "a whole-repo lane is still prompted to prepare for compaction" "echo \"\$C3\" | grep -q 'prepare-for-compact.md'"
echo "== zone-guard: $PASS passed, $FAIL failed"
rm -rf "$T"
[ "$FAIL" = 0 ]
