#!/bin/bash
# zone/tests/zone-guard-stop-push.sh: the zone guard's stop hook (zone-guard.py mode_stop, step 2)
# counts a turn as pushed only when a Bash command RUNS a push. Before
# the change it matched the words `git push`, `push-up` and `zone-tool ledger close` anywhere in a
# command, so a say line, a ledger row, a commit message, an echo, a grep or a heredoc that names
# push-up sent the turn back to file a note (five false stops). Rows: the commands that only name
# a push must not block; the commands that run one (codeteam push-up by any path, codeteam2 push-up,
# git push with and without -C or -c, zone-tool ledger close, bash -c, eval, env and VAR= prefixes,
# segments after then or do) must block when no note follows; a push followed by
# a note tool call must not block. The note tool is CODETEAM_NOTE_TOOLS=file_note, so a tool named
# mcp__notes__file_note counts; with CODETEAM_NOTE_TOOLS unset nothing blocks (the last row). Each row is a fresh python3 running `zone-guard.py stop` on a JSONL
# transcript under $TMPDIR (removed on exit). Nothing reaches the live ledger, a team or the real
# audit log: HOME is the scratch folder for the guard, CODETEAM_BIN is /usr/bin/true, the lane is
# scratch. A row whose guard exits non-zero or logs error_fail_open fails rather than passing.
# 25 rows, two python3 starts each (one writes the transcript, one runs the guard), a few seconds in all. No sleeps, no network.
root="$(cd "$(dirname "$0")/../.." && pwd)"
G="$root/share/claude-hooks/zone-guard.py"
T="$(mktemp -d "${TMPDIR:-/tmp}/zone-guard-stop-push.XXXXXX")"
trap 'rm -rf "$T"' EXIT
# Same result from a lane session as from a plain shell: clear every CODETEAM_* and CT_* the caller
# exported, then set a scratch lane (zone-guard-orc-owns.sh does the same).
for v in $(compgen -e); do case "$v" in CODETEAM_*|CT_*) unset "$v";; esac; done
mkdir -p "$T/rows" "$T/home" "$T/lane/repo"
export CODETEAM_SESSION=zone-test CODETEAM_SWT="$T/lane/repo" CODETEAM_BIN=/usr/bin/true \
  CODETEAM_MANIFEST="$T/none.toml" CODETEAM_NOTE_TOOLS=file_note
PASS=0; FAIL=0; NROW=0

# mk FILE COMMAND NOTE(yes|no): a transcript with a user prompt, one Bash tool_use running COMMAND,
# and a note tool_use (mcp__notes__file_note) after it when NOTE is yes.
mk() {
  python3 -c '
import json, sys
path, cmd, note = sys.argv[1], sys.argv[2], sys.argv[3] == "yes"
rows = [{"type": "user", "message": {"content": "go"}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": cmd}}]}}]
if note:
    rows.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "mcp__notes__file_note", "input": {"content": "note"}}]}})
with open(path, "w") as f:
    f.write("".join(json.dumps(r) + "\n" for r in rows))
' "$1" "$2" "$3"
}

# check block|pass LABEL COMMAND [NOTE]: runs the stop hook on the row and compares the result.
check() {
  want="$1"; label="$2"; cmd="$3"; note="${4:-no}"
  NROW=$((NROW + 1)); tr="$T/rows/$NROW.jsonl"
  mk "$tr" "$cmd" "$note"
  rm -f "$T/home/.claude/audit/hook-events.log"
  out=$(printf '{"transcript_path": "%s"}' "$tr" | HOME="$T/home" python3 "$G" stop 2>/dev/null)
  rc=$?
  if [ "$rc" -ne 0 ] || grep -q error_fail_open "$T/home/.claude/audit/hook-events.log" 2>/dev/null; then
    FAIL=$((FAIL + 1)); echo "  FAIL $label (the guard errored, exit $rc)"; return
  fi
  case "$out" in *'"decision": "block"'*) got=block;; *) got=pass;; esac
  if [ "$got" = "$want" ]; then
    PASS=$((PASS + 1)); echo "  PASS $label"
  else
    FAIL=$((FAIL + 1)); echo "  FAIL $label (stop $got, wanted $want)"
  fi
}

heredoc="cat > /tmp/x <<'EOF'
git push origin main
codeteam push-up m z
EOF"

# False positives: a command that only names a push. None of these may block.
check pass "say line naming push-up-orc-owns does not block" \
  'codeteam say teams/x.toml zone codeteam NOTE zone "push-up-orc-owns landed"'
check pass "zone-tool ledger add of a feature named push-up-x does not block" \
  'bin/zone-tool ledger add push-up-x "row"'
check pass "zone-tool ledger stage of push-up-x does not block" \
  'bin/zone-tool ledger stage push-up-x'
check pass "git commit whose -m names push-up does not block" \
  'git commit -m "fix push-up check"'
check pass "echo of git push does not block" \
  'echo "git push"'
check pass "grep for push-up does not block" \
  'grep -n push-up ledger/issues.md'
check pass "heredoc body naming git push and codeteam push-up does not block" "$heredoc"
check pass "rg for git push or push-up does not block" \
  "rg 'git push|push-up' share"

# True positives: a command that runs a push or a close, with no note after it. All must block.
check block "codeteam push-up blocks" \
  'codeteam push-up teams/codeteam.toml zone -f feat -m "msg"'
check block "codeteam push-up by full path blocks" \
  '/opt/codeteam/bin/codeteam push-up teams/codeteam.toml zone -f feat -m msg'
check block "codeteam2 push-up blocks" \
  'v2/bin/codeteam2 push-up teams/codeteam.toml zone -f feat -m msg'
check block "git push blocks" \
  'git push origin lane/zone'
check block "git -C dir push blocks" \
  'git -C /tmp/repo push'
check block "zone-tool ledger close blocks" \
  'bin/zone-tool ledger close feat'
check block "git push after cd and && blocks" \
  'cd /tmp && git push'
check block "python3 bin/codeteam push-up blocks" \
  'python3 bin/codeteam push-up m z -f f -m x'
check block "bash -c with git push blocks" \
  'bash -c "git push origin x"'

# Contract forms the row list above does not name: git -c k=v before push, eval, env and VAR= prefixes,
# and a segment after then or do.
check block "git -c k=v push blocks" \
  'git -c user.name=x push origin main'
check block "eval of git push blocks" \
  'eval "git push origin x"'
check block "env prefix before git push blocks" \
  'env GIT_TERMINAL_PROMPT=0 git push origin x'
check block "VAR= prefix before git push blocks" \
  'FOO=1 git push origin x'
check block "git push after then blocks" \
  'if true; then git push origin x; fi'
check block "git push after do blocks" \
  'for i in 1; do git push origin x; done'

# A push followed by a note: the turn is not sent back.
check pass "git push followed by a note tool call does not block" \
  'git push origin lane/zone' yes

# With CODETEAM_NOTE_TOOLS unset there is no note check: a push never blocks.
CODETEAM_NOTE_TOOLS= check pass "git push with CODETEAM_NOTE_TOOLS unset does not block" \
  'git push origin lane/zone'

echo "== zone-guard-stop-push: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
