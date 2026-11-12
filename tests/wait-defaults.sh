#!/bin/bash
# zone-tool job wait and watch-agent block for the session's Bash limit less a minute by default, not 540 s
#; 540 s when no limit is set.
HERE=$(cd "$(dirname "$0")/.." && pwd)
exec python3 -I - "$HERE" <<'PY'
import importlib.machinery, importlib.util, os, sys
here = sys.argv[1]
def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader); m = importlib.util.module_from_spec(spec); loader.exec_module(m); return m
zt = load("zone_tool", f"{here}/bin/zone-tool"); wa = load("watch_agent", f"{here}/bin/watch-agent")
got = []
zt.wait_job = lambda q, t, secs: (got.append(secs) or (0, None))
zt.queue_dir = lambda: "/nonexistent"
fail = 0
def check(label, want, val):
    global fail
    ok = val == want; fail |= not ok
    print(f"  {'PASS' if ok else 'FAIL'} {label}: {val}" + ("" if ok else f" (wanted {want})"))
T = "20261105-000000-abcdef"
for env, want_zt, want_wa, label in (("1800000", 1740.0, 1740, "30-minute limit"), (None, 540, 540, "no limit set"),
                                     ("60000", 30.0, 30, "1-minute limit (floor 30 s)")):
    if env is None: os.environ.pop("BASH_DEFAULT_TIMEOUT_MS", None)
    else: os.environ["BASH_DEFAULT_TIMEOUT_MS"] = env
    got.clear()
    try: zt.cmd_job_wait([T])
    except SystemExit: pass
    check(f"job wait default, {label}", want_zt, got[0] if got else None)
    check(f"watch-agent default, {label}", want_wa, wa.default_max())
os.environ["BASH_DEFAULT_TIMEOUT_MS"] = "1800000"; got.clear()
zt.cmd_job_wait([T, "--max", "120"]); check("job wait --max still wins", 120.0, got[0] if got else None)
sys.exit(fail)
PY
