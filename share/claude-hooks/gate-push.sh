#!/usr/bin/env bash
# PreToolUse/Bash hook — gates git push commands against safety
# checks: uncommitted files and last-commit author identity.
# Pass-through on any non-`git push` Bash command.
# CODETEAM_PUSH_AUTHORS: the author-email local parts (an ERE alternation)
# a pushed commit may carry; the default is the stock personas.
#
# Default mode: WARN. CLAUDE_HOOK_MODE=block flips to BLOCK.

set -euo pipefail

MODE="${CLAUDE_HOOK_MODE:-block}"
AUDIT_DIR="${HOME}/.claude/audit"
AUDIT_LOG="${AUDIT_DIR}/hook-events.log"
RAW_DIR="${AUDIT_DIR}/raw"
mkdir -p "$AUDIT_DIR" "$RAW_DIR"

ts="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

stdin_raw="$(cat)"
echo "$stdin_raw" > "$RAW_DIR/preToolUse-Bash-${ts//[:T]/-}-$$.json"

# Parse the bash command; only act on git push
bash_command=""
if command -v jq >/dev/null 2>&1; then
    bash_command="$(printf '%s' "$stdin_raw" | jq -r '.tool_input.command // .input.command // ""' 2>/dev/null || printf '')"
fi

# Only gate git push commands; everything else passes through
case "$bash_command" in
    *"git push"*|*"git -C "*" push"*) ;;
    *)
        echo "${ts} | gate-push | mode=${MODE} | result=passthrough | reason=not_git_push" >> "$AUDIT_LOG"
        exit 0
        ;;
esac

# The repo the push targets, not the session's directory: `git -C <dir> push` and
# `cd <dir> && ... git push` name it in the command (judging the session's own folder
# blocked pushes on the wrong repo's untracked files, or found no repo at all).
target_dir="$(printf '%s' "$bash_command" | python3 -c '
import re, shlex, sys, os
c = sys.stdin.read()
m = re.search(r"git\s+-C\s+(\"[^\"]+\"|\x27[^\x27]+\x27|\S+)[^;&|]*\bpush\b", c)
if not m:
    m = re.search(r"(?:^|&&|;)\s*cd\s+(\"[^\"]+\"|\x27[^\x27]+\x27|\S+)\s*(?:&&|;)[^;|]*\bgit\b[^;&|]*\bpush\b", c)
print(os.path.expanduser(m.group(1).strip("\"\x27")) if m else ".")
' 2>/dev/null || printf '.')"
repo_root=""
branch=""
if git -C "$target_dir" rev-parse --show-toplevel >/dev/null 2>&1; then
    repo_root="$(git -C "$target_dir" rev-parse --show-toplevel 2>/dev/null || printf '')"
    branch="$(git -C "$target_dir" rev-parse --abbrev-ref HEAD 2>/dev/null || printf '')"
fi
if [ -z "$repo_root" ]; then
    # Cannot tell which repo this push targets: stand aside rather than block on a guess.
    echo "${ts} | gate-push | mode=${MODE} | result=passthrough | reason=target_unknown | dir=${target_dir}" >> "$AUDIT_LOG"
    exit 0
fi

# Check 1: uncommitted files in working tree (covers staged,
# unstaged, AND untracked via porcelain)
dirty=0
if [ -n "$repo_root" ]; then
    # Tracked changes only: a push carries commits, and untracked scratch files never travel.
    if [ -n "$(git -C "$repo_root" status --porcelain --untracked-files=no 2>/dev/null || true)" ]; then
        dirty=1
    fi
fi

# Check 2: last commit author signature
last_author_email=""
if [ -n "$repo_root" ]; then
    last_author_email="$(git -C "$repo_root" log -1 --format='%ae' 2>/dev/null || printf '')"
fi

# Compose violations list
violations=""
if [ "$dirty" = "1" ]; then
    violations="${violations}uncommitted_files; "
fi
if [ -z "$last_author_email" ] || \
   ! printf '%s' "$last_author_email" | grep -E "(${CODETEAM_PUSH_AUTHORS:-skippy|bilby|smythe|adams|nagatha|simms|kong})@" >/dev/null 2>&1; then
    violations="${violations}unrecognized_commit_author=${last_author_email}; "
fi

if [ -z "$violations" ]; then
    echo "${ts} | gate-push | mode=${MODE} | result=allow | repo=${repo_root} | branch=${branch}" >> "$AUDIT_LOG"
    exit 0
fi

# Violations present
if [ "$MODE" = "block" ]; then
    echo "${ts} | gate-push | mode=${MODE} | result=block | repo=${repo_root} | branch=${branch} | violations=${violations}" >> "$AUDIT_LOG"
    cat <<JSON
{"permissionDecision": "deny", "reason": "git push to ${repo_root} (branch ${branch}) blocked. Violations: ${violations}If push is intentional and the violations are expected, set CLAUDE_HOOK_MODE=warn for this session OR fix the violations and retry."}
JSON
    exit 0
else
    echo "${ts} | gate-push | mode=${MODE} | result=warn | repo=${repo_root} | branch=${branch} | violations=${violations}" >> "$AUDIT_LOG"
    exit 0
fi
