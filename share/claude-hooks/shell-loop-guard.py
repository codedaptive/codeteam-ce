#!/usr/bin/env python3
"""PreToolUse on Bash, every team: a command holding a shell loop is refused with rule 6's reason .

Claude Code's own check stops a compound command it cannot rule rm out of ("Dangerous rm operation not ruled out")
with a dialog, even under bypassPermissions, and the lead then waits for the owner. Refusing the loop
first gives the lead the reason at once: it rewrites the command and no dialog comes. This hook never approves
anything; every other call goes on unchanged, and so does any call whose input it cannot read."""
import json
import sys
from pathlib import Path

REASON = "Rule 6: one plain command per shell call; use the Grep and Glob tools for searches."


def decide(raw):
    """The hook's stdout for one call's input: the refusal, or "" to let the call through."""
    try:
        sys.dont_write_bytecode = True          # no __pycache__ beside the hooks in production's checkout
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from shell_loop import has_loop
        data = json.loads(raw)
        command = (data.get("tool_input") or {}).get("command") if data.get("tool_name") == "Bash" else None
        if not isinstance(command, str) or not has_loop(command):
            return ""
    except Exception:          # unreadable input or a fault here: the call goes through
        return ""
    return json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                              "permissionDecisionReason": REASON}})


if __name__ == "__main__":
    try:
        out = decide(sys.stdin.read())
    except Exception:
        out = ""
    if out:
        print(out)
