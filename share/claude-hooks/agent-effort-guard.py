#!/usr/bin/env python3
"""PreToolUse hook on Agent|Task (roster v3, 2026-10-25).

A parent may not set `effort` or `model` when it starts a subagent: the agent file sets both,
from roster.md (direct mode) or the proxy alias (alias mode). Found 10-25: Sol coders set
effort=max on 212 of 767 runner starts, overriding runner's effort=low.

2026-10-26: the hook drops the fields and lets the call through (updatedInput) instead of
refusing it. A refusal made the lead retry, and auto mode's classifier read the retry as a way
around a block and denied it, which held five lanes' work. Each drop is still logged to
$CODETEAM_HOME/scratchpad/usage/agent-effort-guard.log (read by the analysis; CODETEAM_HOME defaults
to the checkout this hook lives in).
"""
import json, os, sys, time

from pathlib import Path
CT_HOME = Path(os.environ.get("CODETEAM_HOME") or Path(__file__).resolve().parents[2])
LOG = str(CT_HOME / "scratchpad" / "usage" / "agent-effort-guard.log")


def main():
    try:
        d = json.load(sys.stdin)
    except ValueError:
        return 0
    if d.get("tool_name") not in ("Agent", "Task"):
        return 0
    inp = d.get("tool_input") or {}
    set_keys = [k for k in ("effort", "model") if inp.get(k) not in (None, "")]
    if not set_keys:
        return 0
    agent = inp.get("subagent_type", "?")
    try:
        with open(LOG, "a") as f:
            f.write(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "session": d.get("session_id"),
                                "agent": agent, "set": {k: inp.get(k) for k in set_keys},
                                "action": "dropped"}) + "\n")
    except OSError:
        pass
    kept = {k: v for k, v in inp.items() if k not in ("effort", "model")}
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "permissionDecisionReason": f"{agent} started with its own agent file's model and effort; "
                                    f"the {' and '.join(set_keys)} given was dropped",
        "updatedInput": kept}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
