#!/bin/bash
# zone-tool's test guards: the type-check first, no whole rerun straight after a FAIL, and a
# budget of whole runs per request worktree. Exercises guard_run directly: nothing is queued.
set -u
HERE=$(cd "$(dirname "$0")/.." && pwd)
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
export GIT_CEILING_DIRECTORIES="$W"
R="$W/team-x/workcrews/a/requests/agent-1"; mkdir -p "$R/pk/A"
cd "$R" && git init -q && echo a > pk/A/a.rs && printf 'check:\n\t@test ! -f BROKEN || { echo "error[E0425]: cannot find value"; exit 1; }\n' > Makefile
git add -A && git -c user.email=t@t -c user.name=t commit -qm init
unset ZONE_CHECK_CMD ZONE_CHECK ZONE_WHOLE_BUDGET CODETEAM_BUILDQ_TICKET
python3 - "$HERE/bin/zone-tool" "$R" <<'PY'
import importlib.machinery, importlib.util, json, sys, os
from pathlib import Path
l = importlib.machinery.SourceFileLoader("zt", sys.argv[1]); sp = importlib.util.spec_from_loader("zt", l)
zt = importlib.util.module_from_spec(sp); l.exec_module(zt)
root = Path(sys.argv[2]); os.chdir(root); fail = 0
def h(): return zt.code_hash(root, None, zt.snapshot(root))
def t(label, cond):
    global fail
    print(("  PASS " if cond else "  FAIL ") + label); fail |= not cond
def rec(key, result, time):
    zt.record_path(root, key).write_text(json.dumps({"key": key, "result": result, "time": time, "tail": ["boom"]}))
t("clean check, first whole run: allowed", zt.guard_run(root, "one pk/A", h(), False) is None)
(root / "BROKEN").write_text("x")
r = zt.guard_run(root, "one pk/A", h(), False)
t("check fails: refused, with the check's errors", r and "REFUSED" in r and "E0425" in r)
t("check fails: a filtered run is refused too", "REFUSED" in (zt.guard_run(root, "one pk/A --filter X", h(), False) or ""))
t("joining an identical queued job is never refused", zt.guard_run(root, "one pk/A", h(), True) is None)
(root / "BROKEN").unlink()
rec("one pk/A", "FAIL", "2026-11-06T10:00:00-06:00")
r = zt.guard_run(root, "one pk/A", h(), False)
t("whole rerun after a whole FAIL, no filtered pass since: refused", r and "FAILED" in r)
t("a filtered run of the failing tests is allowed", zt.guard_run(root, "one pk/A --filter X", h(), False) is None)
rec("one pk/A --filter X", "PASS", "2026-11-06T10:05:00-06:00")
t("after the filtered pass, the whole run is allowed", zt.guard_run(root, "one pk/A", h(), False) is None)
rec("one pk/A", "PASS", "2026-11-06T10:10:00-06:00")
for i in range(2): zt.guard_run(root, "one pk/A", h(), False)
r = zt.guard_run(root, "one pk/A", h(), False)
t("fifth whole run in a request worktree: refused (budget 4)", r and "used its 4 whole runs" in r)
t("filtered runs are not counted against the budget", zt.guard_run(root, "one pk/A --filter Y", h(), False) is None)
zt.cmd_grant([str(root), "one", "pk/A", "--reason", "review round 3"])
t("after a grant: one more whole run", zt.guard_run(root, "one pk/A", h(), False) is None)
t("and then refused again", "REFUSED" in (zt.guard_run(root, "one pk/A", h(), False) or ""))
os.environ["ZONE_CHECK"] = "0"; (root / "BROKEN").write_text("x")
t("ZONE_CHECK=0 turns the check off", "type-check" not in (zt.guard_run(root, "one pk/B", h(), False) or ""))
sys.exit(fail)
PY
