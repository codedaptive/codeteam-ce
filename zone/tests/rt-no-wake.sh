#!/bin/bash
# zone/tests/rt-no-wake.sh: check the codeteam-rt command surface and importable helpers.
# 1. py_compile on a copy of bin/codeteam-rt exits 0.
# 2. `wake` is refused as an unknown command: exit 2 and "invalid choice" on stderr. CODETEAM_REGISTRY
#    is unset and --registry points to a scratch path to isolate any registry access.
# 3. `--help` does not mention wake and lists watch, send, register, tick, sweep and status.
# 4. Loaded by path the way bin/codeteam's _rt() loads it, alive, precise_kill, proc_command, wait_gone
#    and compact_count are callable.
# 5. The same load: cmd_watch, cmd_send, cmd_register, cmd_tick, cmd_sweep, cmd_status and make_target
#    are callable.
# 6. The same load: cmd_wake, watcher_running and NUDGE_EVERY are absent.
# 7. The load does not run main(), which is guarded by __name__: it returns with no subcommand in argv.
# Bytecode goes to the scratch dir (PYTHONPYCACHEPREFIX), so no __pycache__ lands in bin/.
set -u
here="$(cd "$(dirname "$0")/../.." && pwd)"
rt="$here/bin/codeteam-rt"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
unset CODETEAM_REGISTRY
export PYTHONPYCACHEPREFIX="$tmp/pycache"
py=python3
[ -x "$py" ] || py=python3
fail=0

cp "$rt" "$tmp/codeteam_rt_copy.py"
if "$py" -m py_compile "$tmp/codeteam_rt_copy.py"; then echo "ok   codeteam-rt compiles"
else echo "FAIL codeteam-rt does not compile"; fail=1; fi

"$py" "$rt" --registry "$tmp/reg.json" wake >/dev/null 2>"$tmp/wake.err"; code=$?
if [ "$code" = 2 ] && grep -q "invalid choice" "$tmp/wake.err"; then echo "ok   wake is refused as an unknown command"
else echo "FAIL wake: exit $code, stderr [$(tr '\n' ' ' < "$tmp/wake.err")]"; fail=1; fi

help="$("$py" "$rt" --help 2>&1)"; hcode=$?
case "$help" in *wake*) wake_listed=1;; *) wake_listed=0;; esac
missing=""
for c in watch send register tick sweep status; do
  case "$help" in *"$c"*) ;; *) missing="$missing $c";; esac
done
if [ "$hcode" = 0 ] && [ "$wake_listed" = 0 ] && [ -z "$missing" ]; then
  echo "ok   --help has no wake and lists watch, send, register, tick, sweep and status"
else echo "FAIL --help: exit $hcode, wake listed=$wake_listed, not listed:$missing"; fail=1; fi

"$py" - "$rt" <<'PY' || fail=1
import importlib.util
import sys
from importlib.machinery import SourceFileLoader

path = sys.argv[1]
sys.argv = [path]
spec = importlib.util.spec_from_loader("codeteam_rt", SourceFileLoader("codeteam_rt", path))
rt = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(rt)
except SystemExit as e:
    print(f"FAIL loading by path ran main() and exited {e.code}")
    sys.exit(1)
print("ok   loading by path does not run main()")

RT_HELPERS = ("alive", "precise_kill", "proc_command", "wait_gone", "compact_count")
COMMANDS = ("cmd_watch", "cmd_send", "cmd_register", "cmd_tick", "cmd_sweep", "cmd_status", "make_target")
GONE = ("cmd_wake", "watcher_running", "NUDGE_EVERY")
failures = []


def report(ok, good, problem):
    print(f"ok   {good}" if ok else f"FAIL {problem}")
    if not ok:
        failures.append(problem)


def not_callable(names):
    return [n for n in names if not callable(getattr(rt, n, None))]


missing = not_callable(RT_HELPERS)
report(not missing, "the five _rt() helpers are callable", f"missing: {' '.join(missing)}")
missing = not_callable(COMMANDS)
report(not missing, "cmd_watch, cmd_send, cmd_register, cmd_tick, cmd_sweep, cmd_status and make_target are callable",
       f"missing: {' '.join(missing)}")
left = [n for n in GONE if hasattr(rt, n)]
report(not left, "cmd_wake, watcher_running and NUDGE_EVERY are absent", f"still present: {' '.join(left)}")
sys.exit(1 if failures else 0)
PY

exit $fail
