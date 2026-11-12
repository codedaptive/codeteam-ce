#!/usr/bin/env -S python3 -u
"""codeteam-watchdog's queue sweep: a queued build job whose process is gone is cancelled; of the same build running
twice in one tree, the older is stopped; test jobs are left alone (2026-11-08). A throwaway queue folder."""
import importlib.machinery, importlib.util, json, subprocess, sys, tempfile, time
from pathlib import Path
ld = importlib.machinery.SourceFileLoader("wd", str(Path(__file__).resolve().parents[1] / "bin" / "codeteam-watchdog"))
sp = importlib.util.spec_from_loader("wd", ld); wd = importlib.util.module_from_spec(sp); ld.exec_module(wd)
wd.notify = lambda *a: None
q = Path(tempfile.mkdtemp(prefix="sweep-")); fails = 0
def t(label, cond, detail=""):
    global fails; print(("  PASS " if cond else "  FAIL ") + label + ("" if cond else f"  [{detail}]")); fails += not cond
def job(ticket, state, pid, cmd=("cargo", "check"), kind="slot", wt="/w/a", sub=0.0, tool="sleep"):
    (q / f"{ticket}.json").write_text(json.dumps({"ticket": ticket, "kind": kind, "class": "dev", "state": state,
        "pid": pid, "command": list(cmd), "worktree": wt, "submitted": sub, "key": "slot cargo", "test_flags": [], "record": None, "tool": tool}))
dead = subprocess.Popen(["true"]); dead.wait()
old = subprocess.Popen(["sleep", "60"]); new = subprocess.Popen(["sleep", "60"]); other = subprocess.Popen(["sleep", "60"])
job("20261108-000001-aaaaaa", "queued", dead.pid)
job("20261108-000002-bbbbbb", "running", old.pid, sub=1)
job("20261108-000003-cccccc", "running", new.pid, sub=2)
job("20261108-000004-dddddd", "running", other.pid, cmd=("cargo", "test"), sub=3)
job("20261108-000005-eeeeee", "queued", dead.pid, kind="run")
# stale job files whose pids now belong to other programs: never counted, never signalled
s1 = subprocess.Popen(["sleep", "60"]); s2 = subprocess.Popen(["sleep", "60"])
job("20261108-000006-ffffff", "running", s1.pid, wt="/w/b", sub=1, tool="cargo")
job("20261108-000007-gggggg", "running", s2.pid, wt="/w/b", sub=2, tool="cargo")
lines = wd.sweep_queue(q)
time.sleep(0.5)
t("a queued build whose process is gone is cancelled", json.loads((q / "20261108-000001-aaaaaa.json").read_text())["state"] == "broken", lines)
t("the older of two identical running builds is stopped", old.poll() is not None)
t("the newer one runs on", new.poll() is None)
t("a different build in the same tree runs on", other.poll() is None)
t("a test job is left alone", json.loads((q / "20261108-000005-eeeeee.json").read_text())["state"] == "queued")
t("a process that is not the job's tool is never stopped", s1.poll() is None and s2.poll() is None)
for p in (new, other, s1, s2):
    p.kill()
print("all passed" if not fails else f"{fails} failed"); sys.exit(1 if fails else 0)
