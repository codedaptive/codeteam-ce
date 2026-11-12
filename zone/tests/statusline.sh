#!/bin/bash
# zone/tests/statusline.sh: bin/codeteam-statusline's metrics line.
# 1. A project with no .claude/hooks/ gets the metrics line from share/'s
#    capture-metrics.sh.
# 2. A project's own .claude/hooks/capture-metrics.sh wins over share/'s.
# Metrics logs go to a scratch CLAUDE_METRICS_DIR, never the real one.
set -u
here="$(cd "$(dirname "$0")/../.." && pwd)"
sl="$here/bin/codeteam-statusline"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
export CLAUDE_METRICS_DIR="$tmp/metrics"
payload='{"model":{"display_name":"Opus"},"context_window":{"total_input_tokens":1500,"total_output_tokens":500},"cost":{"total_cost_usd":1.25},"effort":{"level":"high"},"session_id":"s","workspace":{"current_dir":"'"$tmp"'/proj"}}'
fail=0

mkdir -p "$tmp/bare"
got="$(printf '%s' "$payload" | CLAUDE_PROJECT_DIR="$tmp/bare" "$sl")"
want='[Opus] 2k tok  $1.25  Effort: high'
if [ "$got" = "$want" ]; then echo "ok   no .claude/hooks: share/ fallback gives the metrics line"
else echo "FAIL no .claude/hooks: got [$got], want [$want]"; fail=1; fi

mkdir -p "$tmp/own/.claude/hooks"
printf '#!/bin/sh\ncat >/dev/null\necho PROJECT-HOOK\n' > "$tmp/own/.claude/hooks/capture-metrics.sh"
chmod +x "$tmp/own/.claude/hooks/capture-metrics.sh"
got="$(printf '%s' "$payload" | CLAUDE_PROJECT_DIR="$tmp/own" "$sl")"
want='PROJECT-HOOK  Effort: high'
if [ "$got" = "$want" ]; then echo "ok   project's own capture-metrics.sh wins"
else echo "FAIL project hook: got [$got], want [$want]"; fail=1; fi

exit $fail
