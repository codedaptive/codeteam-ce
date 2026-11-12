#!/usr/bin/env -S python3 -u
"""codeteam-slot waits for the same build already running in the same tree instead of starting it twice (2026-11-08)."""
import importlib.machinery, importlib.util, json, os, subprocess, sys, tempfile
from pathlib import Path
ld = importlib.machinery.SourceFileLoader("slot", str(Path(__file__).resolve().parents[1] / "bin" / "codeteam-slot"))
sp = importlib.util.spec_from_loader("slot", ld); slot = importlib.util.module_from_spec(sp); ld.exec_module(slot)
q = Path(tempfile.mkdtemp(prefix="slot-same-")); fails = 0
def t(label, cond):
    global fails; print(("  PASS " if cond else "  FAIL ") + label); fails += not cond
wt = slot.build_worktree()
other = subprocess.Popen(["sleep", "30"])
(q / "a.json").write_text(json.dumps({"ticket": "a", "kind": "slot", "state": "running", "worktree": wt,
                                      "command": ["cargo", "check"], "pid": other.pid}))
t("the same command in the same tree, still running, is found", (slot.same_build_running(q, "cargo", ["check"]) or {}).get("ticket") == "a")
t("another command is not", slot.same_build_running(q, "cargo", ["test"]) is None)
other.kill(); other.wait()
t("a job whose process is gone is not", slot.same_build_running(q, "cargo", ["check"]) is None)
print("all passed" if not fails else f"{fails} failed"); sys.exit(1 if fails else 0)
