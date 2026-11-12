#!/bin/bash
# Runs the checkout's own bin/codeteam-rt against fake sessions in a private tmux socket (-L ctest), inside a
# mktemp folder that an EXIT trap removes. CODETEAM_RT overrides the tool path (default: this checkout's tool).
# type_line in bin/codeteam-rt is a no-op, so the scenario labels (typed /compact, /exit, compaction confirmed)
# and the typed/cleaned lines are informational echoes that are never compared. Setup exits 2 on a missing
# tool or tmux and 1 on a failed cd or mktemp; after that a run fails when a die() guard trips: a codeteam-rt
# call, tmux or fixture setup, mkdir, mv, the python registry edit, a missing decoy, a decoy not alive after C2 or
# after D, or an empty idle-check name.
# The run ends with "run-test.sh: ok" and status 0.
set -u
set -o pipefail
die() { echo "run-test.sh: $*" >&2; exit 1; }
HERE=$(cd "$(dirname "$0")" && pwd) || exit 1
ROOT=$(cd "$HERE/../.." && pwd) || exit 1
RT=${CODETEAM_RT:-$ROOT/bin/codeteam-rt}
if [ ! -x "$RT" ] || [ -d "$RT" ]; then echo "run-test.sh: codeteam-rt missing or not executable: $RT" >&2; exit 2; fi
command -v tmux >/dev/null 2>&1 || { echo "run-test.sh: tmux not found on PATH" >&2; exit 2; }

T=""; DECOY=""; FEEDER=""
cleanup() {
  [ -n "${DECOY:-}" ] && kill "$DECOY" 2>/dev/null
  [ -n "${FEEDER:-}" ] && kill "$FEEDER" 2>/dev/null
  tmux -L ctest kill-server 2>/dev/null
  case "${T:-}" in */ct-rt.*) [ -d "$T" ] && rm -rf -- "$T" ;; esac
}
trap cleanup EXIT
trap 'exit 1' INT TERM HUP
T0=$(mktemp -d "${TMPDIR:-/tmp}/ct-rt.XXXXXX") || exit 1
if [ -z "$T0" ] || [ ! -d "$T0" ]; then echo "run-test.sh: mktemp gave no folder: '$T0'" >&2; exit 1; fi
T=$T0
cp "$HERE/launch-fake" "$HERE/claude-fake" "$T/" || die "copy fixtures into $T"
cd "$T" || exit 1
export CODETEAM_REGISTRY="$T/registry.json" CT_RT_DIR="$T" CODETEAM_RT="$RT" CT_TMUX_SOCKET=ctest CT_COMPACT_HOURS=0.001 CT_EXIT_HOURS=0.002 CT_EXIT_WAIT=3 CT_KILL_WAIT=3
tmux -L ctest kill-server 2>/dev/null; tmux -L ctest new-session -d -s ct -n base || die "tmux new-session"
./launch-fake A 0 >/dev/null || die "./launch-fake A"
./launch-fake B 1 >/dev/null || die "./launch-fake B"
(cd B/swt && sleep 100000 | STUBBORN=1 python3 "$T/claude-fake" B "$T/B/decoy.jsonl" >/dev/null 2>&1 &)
sleep 0.5
# The decoy is the claude-fake process on this run's decoy transcript; its feeder is the sleep beside it.
for _ in 1 2 3 4 5 6 7 8 9 10; do
  DECOY=$(ps -ww -eo pid,args | awk -v t="$T/B/decoy.jsonl" 'index($0, t) && !/awk/ {print $1}' | head -1)
  [ -n "$DECOY" ] && break
  sleep 0.5
done
[ -n "$DECOY" ] || die "decoy did not start"
DECOY_PPID=$(ps -ww -o ppid= -p "$DECOY" | tr -d ' ')
if [ -n "$DECOY_PPID" ]; then
  FEEDER=$(ps -ww -eo pid,ppid,args | awk -v pp="$DECOY_PPID" '$2==pp && /sleep 100000/ && !/awk/ {print $1}' | head -1)
fi
echo "== E watcher"; mkdir -p W/inbox W/outbox || die "mkdir W"; (sleep 1; echo hi > W/inbox/m1.md) & "$RT" watch W/inbox --timeout 5 --interval 0.2 || die "codeteam-rt watch (1)"; echo hi > W/outbox/m1.md; "$RT" watch W/inbox --timeout 1 --interval 0.2 || die "codeteam-rt watch (2)"
echo "== A1 tick at ~4s idle: expect /compact for A and B"; sleep 4; "$RT" tick | sed 's/^[^ ]* //' || die "codeteam-rt tick (A1)"
sleep 1; echo "A typed: $(tr '\n' ' ' < A/A.typed)"
echo "== A2 tick: expect compaction confirmed"; "$RT" tick | sed 's/^[^ ]* //' || die "codeteam-rt tick (A2)"
echo "== A3 tick at ~8s: A /exit -> asleep + clean; B stubborn -> idle check"; sleep 3; "$RT" tick | sed 's/^[^ ]* //' || die "codeteam-rt tick (A3)"
echo "A cleaned: $(wc -l < A/swt/cleaned 2>/dev/null || echo 0)"; IC=$(ls B/mail/inbox | grep _idle | head -1); echo "B idle-check file: $IC"
[ -n "$IC" ] || die "no idle-check file in B/mail/inbox after A3 tick"
echo "== C1 B answers busy"; echo busy > "B/mail/outbox/$IC"; mv "B/mail/inbox/$IC" B/mail/done/ || die "mv idle-check to done"; "$RT" tick | sed 's/^[^ ]* //' || die "codeteam-rt tick (C1)"
echo "== C2 B idle again, no answer -> precise kill"; sleep 8; "$RT" tick | sed 's/^[^ ]* //' || die "codeteam-rt tick (C2a)"; IC2=$(ls B/mail/inbox | grep _idle | head -1); echo "second check: $IC2"
sleep 0.5; "$RT" tick | sed 's/^[^ ]* //' || die "codeteam-rt tick (C2b)"
if kill -0 "$DECOY" 2>/dev/null; then echo "decoy $DECOY alive: yes"; else echo "decoy $DECOY alive: NO"; die "C2: decoy $DECOY is not alive after the precise kill"; fi
echo "== D pid reuse: register D with decoy pid but other cwd"; mkdir -p D/swt D/mail || die "mkdir D"; "$RT" register D --pid "$DECOY" --cwd D/swt --mail D/mail --target tmux:ct:none --launch true >/dev/null || die "codeteam-rt register D"
python3 - <<'P' || die "python3 registry edit (pending_exit for D)"
import json,os; p=os.environ["CODETEAM_REGISTRY"]; d=json.load(open(p)); d["sessions"]["D"]["pending_exit"]="_idle-check-x.md"; json.dump(d,open(p,"w"))
P
"$RT" tick | sed 's/^[^ ]* //' || die "codeteam-rt tick (D)"
if kill -0 "$DECOY" 2>/dev/null; then echo "decoy alive after refused kill: yes"; else echo "decoy alive after refused kill: NO"; die "D: decoy $DECOY is not alive after the refused kill"; fi
echo "== status"; "$RT" status || die "codeteam-rt status"
kill "$DECOY" 2>/dev/null; tmux -L ctest kill-server
echo "run-test.sh: ok"
exit 0
