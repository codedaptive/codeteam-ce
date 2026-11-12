#!/bin/bash
# Runs the checkout's own bin/codeteam-rt against fake sessions in a private tmux socket (-L ctest), inside a
# mktemp folder that an EXIT trap removes. CODETEAM_RT overrides the tool path (default: this checkout's tool).
# type_line in bin/codeteam-rt is a no-op, so the scenario labels (/compact both, confirmed, /compact again, exit)
# are informational echoes that are never compared. Setup exits 2 on a missing tool or tmux and 1 on a failed cd
# or mktemp; after that a run fails when a die() guard trips: a codeteam-rt call, tmux or fixture setup, mv, or
# an empty idle-check name. The run ends with "run-test2.sh: ok" and status 0.
set -u
set -o pipefail
die() { echo "run-test2.sh: $*" >&2; exit 1; }
HERE=$(cd "$(dirname "$0")" && pwd) || exit 1
ROOT=$(cd "$HERE/../.." && pwd) || exit 1
RT=${CODETEAM_RT:-$ROOT/bin/codeteam-rt}
if [ ! -x "$RT" ] || [ -d "$RT" ]; then echo "run-test2.sh: codeteam-rt missing or not executable: $RT" >&2; exit 2; fi
command -v tmux >/dev/null 2>&1 || { echo "run-test2.sh: tmux not found on PATH" >&2; exit 2; }

T=""
cleanup() {
  tmux -L ctest kill-server 2>/dev/null
  case "${T:-}" in */ct-rt.*) [ -d "$T" ] && rm -rf -- "$T" ;; esac
}
trap cleanup EXIT
trap 'exit 1' INT TERM HUP
T0=$(mktemp -d "${TMPDIR:-/tmp}/ct-rt.XXXXXX") || exit 1
if [ -z "$T0" ] || [ ! -d "$T0" ]; then echo "run-test2.sh: mktemp gave no folder: '$T0'" >&2; exit 1; fi
T=$T0
cp "$HERE/launch-fake" "$HERE/claude-fake" "$T/" || die "copy fixtures into $T"
cd "$T" || exit 1
export CODETEAM_REGISTRY="$T/registry.json" CT_RT_DIR="$T" CODETEAM_RT="$RT" CT_TMUX_SOCKET=ctest CT_COMPACT_HOURS=0.002 CT_EXIT_HOURS=0.006 CT_EXIT_WAIT=3 CT_KILL_WAIT=3
tmux -L ctest kill-server 2>/dev/null; tmux -L ctest new-session -d -s ct -n base || die "tmux new-session"
./launch-fake A 0 >/dev/null || die "./launch-fake A"
./launch-fake B 1 >/dev/null || die "./launch-fake B"
echo "== t=0 tick: nothing"; "$RT" tick | sed 's/^[^ ]* //' || die "codeteam-rt tick (t=0)"
echo "== t=8 tick: /compact both"; sleep 8; "$RT" tick | sed 's/^[^ ]* //' || die "codeteam-rt tick (t=8)"; sleep 0.5
echo "== t=9 tick: confirmed"; "$RT" tick | sed 's/^[^ ]* //' || die "codeteam-rt tick (t=9)"
echo "== t=10 tick: nothing new (already compacted this idle stretch)"; "$RT" tick | sed 's/^[^ ]* //' || die "codeteam-rt tick (t=10)"
echo "== activity on A resets idle"; "$RT" send A/mail job "x" >/dev/null || die "codeteam-rt send"; echo ok > A/mail/outbox/job.md; mv A/mail/inbox/job.md A/mail/done/ || die "mv job to done"; "$RT" status > "$T/status.out" || die "codeteam-rt status (first line)"; head -1 "$T/status.out"
echo "== t=23 tick: A /compact again (new idle stretch? no: idle 13s<exit), B -> exit -> idle check"; sleep 13; "$RT" tick | sed 's/^[^ ]* //' || die "codeteam-rt tick (t=23)"
IC=$(ls B/mail/inbox | grep _idle | head -1)
[ -n "$IC" ] || die "no idle-check file in B/mail/inbox after t=23 tick"
echo busy > "B/mail/outbox/$IC"; mv "B/mail/inbox/$IC" B/mail/done/ || die "mv idle-check to done"
echo "== B answered busy"; "$RT" tick | sed 's/^[^ ]* //' || die "codeteam-rt tick (B busy)"; "$RT" status || die "codeteam-rt status"
tmux -L ctest kill-server
echo "run-test2.sh: ok"
exit 0
