#!/usr/bin/env python3
"""Effort modes for the sessions the owner hands control to (repo-designer, repo-orchestrator).

The owner turns a session's effort up or down with /effort; each (role, model family, level) has a mode with its own
instructions in the team's effort ladders (catalog v4 -> team/claude/hooks/effort-ladders.json). This hook:
  SessionStart       gives the launch level's mode (from CODETEAM_EFFORT / CODETEAM_MODEL, set by codeteam).
  UserPromptSubmit   reminds the session of its current mode and its end-of-turn tag (cheap, no extra turn).
  Stop               sees the effort level actually in use; when it changed since the last mode it gave, it
                     holds the stop once and hands over the new mode, which replaces the earlier one.
Only roles and model families that have a ladder are touched; for anything else the hook does nothing.
Usage (settings.json): effort-mode.py   (reads the hook event from stdin)"""
import json, os, re, sys, pathlib

STATE = pathlib.Path(os.environ.get("CODETEAM_EFFORT_STATE", pathlib.Path.home() / ".cache" / "codeteam" / "effort-mode"))
FAMILIES = ("opus", "sonnet", "haiku", "fable", "astra", "sol", "terra", "luna")

def family(model):
    m = (model or "").lower()
    return next((f for f in FAMILIES if f in m), "")

def ladders():
    for p in (os.environ.get("CODETEAM_EFFORT_LADDERS"),
              os.path.join(os.environ.get("CLAUDE_PROJECT_DIR", "."), ".claude", "hooks", "effort-ladders.json")):
        if p and os.path.exists(p):
            return json.load(open(p))
    return {}

def model_from_transcript(path):
    """The model of the latest assistant message (follows /model switches)."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2); f.seek(max(0, f.tell() - 200_000)); tail = f.read().decode("utf-8", "ignore")
        for line in reversed(tail.splitlines()):
            if '"model"' in line and '"assistant"' in line:
                m = re.search(r'"model"\s*:\s*"([^"]+)"', line)
                if m: return m.group(1)
    except OSError:
        pass
    return ""

def rung(L, role, fam, level):
    r = L.get(role, {}).get(fam) or {}
    alias = L.get("_aliases", {}).get(fam)
    if not r and alias:
        r = L.get(role, {}).get(alias) or {}
    return r.get((level or "").lower())

def text_for(level, r):
    return (f"Effort is now {level} ({r['mode']}). This replaces any earlier mode instructions.\n{r['text']}\n"
            f"End every turn with the tag [Mode: {r['mode']}].")

def main():
    d = json.load(sys.stdin)
    ev = d.get("hook_event_name"); sid = d.get("session_id", "x"); role = d.get("agent_type") or ""
    L = ladders()
    if not L or role not in L:
        return 0
    STATE.mkdir(parents=True, exist_ok=True); sf = STATE / f"{sid}.json"
    st = json.load(open(sf)) if sf.exists() else {}
    if ev == "SessionStart":
        level = os.environ.get("CODETEAM_EFFORT", ""); fam = family(d.get("model") or os.environ.get("CODETEAM_MODEL"))
        r = rung(L, role, fam, level)
        if not r: return 0
        json.dump({"level": level, "family": fam, "mode": r["mode"]}, open(sf, "w"))
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text_for(level, r)}}))
    elif ev == "UserPromptSubmit":
        if st.get("mode"):
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                  "additionalContext": f"Current mode: {st['mode']} (effort {st['level']}). End your turn with [Mode: {st['mode']}]."}}))
    elif ev == "Stop":
        level = ((d.get("effort") or {}).get("level") or os.environ.get("CLAUDE_EFFORT") or "").lower()
        fam = family(model_from_transcript(d.get("transcript_path", "")) or os.environ.get("CODETEAM_MODEL")) or st.get("family", "")
        if not level or (level == st.get("level") and fam == st.get("family")):
            return 0
        r = rung(L, role, fam, level)
        if not r:
            json.dump({"level": level, "family": fam, "mode": ""}, open(sf, "w")); return 0
        json.dump({"level": level, "family": fam, "mode": r["mode"]}, open(sf, "w"))
        if d.get("stop_hook_active"):
            return 0
        print(json.dumps({"decision": "block", "reason": text_for(level, r) + "\nAcknowledge the new mode in one line, then end your turn."}))
    return 0

if __name__ == "__main__":
    sys.exit(main())
