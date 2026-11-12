#!/bin/bash
# capture-metrics.sh — statusline hook that logs per-turn metrics and renders
# a compact status line.
#
# Claude Code pipes a JSON payload to the statusline script on stdin after
# every turn: model, context_window, cost, rate limits. We append it to a
# per-folder JSONL so later analysis has cost and token data without any
# manual step, then print one line for the terminal.
#
# Known upstream bug (anthropics/claude-code#13783): context_window carries
# CUMULATIVE session tokens, not current context usage. Treat it as a running
# total, never as a fill percentage.
#
# The /context category split (system / tools / memory / skills / messages)
# is NOT available here (an open Claude Code feature request).
#
# Where the JSONL goes: CLAUDE_METRICS_DIR, else CODETEAM_METRICS_DIR, else
# $CODETEAM_WORKSPACE/metrics (CODETEAM_WORKSPACE defaults to ~/codeteam-work).

set -uo pipefail

INPUT=$(cat)
LOG_DIR="${CLAUDE_METRICS_DIR:-${CODETEAM_METRICS_DIR:-${CODETEAM_WORKSPACE:-$HOME/codeteam-work}/metrics}}"
export CLAUDE_METRICS_DIR="$LOG_DIR"
mkdir -p "$LOG_DIR" 2>/dev/null || true

printf '%s' "$INPUT" | python3 -c '
import json, sys, os, datetime
raw = sys.stdin.read()
try:
    d = json.loads(raw)
except Exception:
    print(""); raise SystemExit(0)

model = (d.get("model") or {}).get("display_name", "?")
cw    = d.get("context_window") or {}
cost  = d.get("cost") or {}
ws    = d.get("workspace") or {}

tin   = cw.get("total_input_tokens", 0) or 0
tout  = cw.get("total_output_tokens", 0) or 0
usd   = cost.get("total_cost_usd", 0) or 0
sid   = d.get("session_id") or "unknown"
cwd   = ws.get("current_dir") or d.get("cwd") or os.getcwd()

# Append the raw payload plus our derived fields. One line per turn.
rec = {
    "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "session_id": sid,
    "cwd": cwd,
    "model": model,
    "total_input_tokens": tin,
    "total_output_tokens": tout,
    "total_cost_usd": usd,
    "raw": d,
}
log_dir = os.environ["CLAUDE_METRICS_DIR"]
try:
    os.makedirs(log_dir, exist_ok=True)
    stream = os.path.basename(cwd)
    path = os.path.join(log_dir, f"{stream}.jsonl")
    line = json.dumps(rec) + "\n"
    # Append under an exclusive lock, single write() call. Two paired
    # sessions on one worktree fire this hook concurrently; an unlocked
    # append interleaves and produces unparseable records. Observed: one
    # file reached 1,371 corrupt lines out of 1,401 after a git conflict
    # landed mid-file and kept being re-appended around.
    #
    # This file is the measurement every token analysis rests on.
    import fcntl
    with open(path, "a") as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except Exception:
            pass          # lock unavailable: still better than not writing
        fh.write(line)
except Exception:
    pass   # never let logging break the status line

tot = tin + tout
print(f"[{model}] {tot/1000:.0f}k tok  ${usd:.2f}")
' 2>/dev/null || echo ""

exit 0
