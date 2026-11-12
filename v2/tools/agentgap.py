"""How long each Agent call made by a team's main sessions (orchestrator, coordinators) held the session
before its result came back: the deaf window. With the team, the
start time and the sessions as arguments. Main-session transcripts only (not subagents/).
Run: python3 -I agentgap.py <team> [since-ISO-UTC] [session-substring]"""
import glob, json, os, re, sys, datetime as D
team = sys.argv[1]; since = sys.argv[2] if len(sys.argv) > 2 else "2026-10-28T22:00"; only = sys.argv[3] if len(sys.argv) > 3 else ""
P = os.path.expanduser("~/.claude/projects"); rows = []
iso = lambda s: D.datetime.fromisoformat(s.replace("Z", "+00:00"))
# Claude Code names a project folder after its path with "/" and "." as "-".
W = re.sub(r"[/.]", "-", os.environ.get("CODETEAM_WORKSPACE") or os.path.expanduser("~/codeteam-work"))
for f in glob.glob(P + f"/{W}-team-{team}-*/*.jsonl"):
    who = f.split(f"team-{team}-")[1].split("/")[0]
    if only and only not in who:
        continue
    st = {}
    for l in open(f, errors="ignore"):
        try: d = json.loads(l)
        except Exception: continue
        ts = d.get("timestamp", "")
        if ts < since: continue
        cont = (d.get("message") or {}).get("content")
        if not isinstance(cont, list): continue
        for b in cont:
            if not isinstance(b, dict): continue
            if b.get("type") == "tool_use" and b.get("name") in ("Agent", "Task"):
                st[b["id"]] = (ts, b["input"].get("run_in_background", "unset"), b["input"].get("subagent_type", ""))
            if b.get("type") == "tool_result" and b.get("tool_use_id") in st:
                t0, bg, at = st.pop(b["tool_use_id"]); t = json.dumps(b.get("content"))
                kind = "async" if "Async agent launched" in t or "background" in t[:300].lower() else "fg"
                rows.append(((iso(ts) - iso(t0)).total_seconds(), kind, bg, at, who, t0[:16]))
    for tid, (t0, bg, at) in st.items():     # still open: holding the session now
        rows.append(((D.datetime.now(D.timezone.utc) - iso(t0)).total_seconds(), "OPEN", bg, at, who, t0[:16]))
rows.sort(reverse=True)
for r in rows[:15]:
    print(f"{r[0]/60:6.1f} min {r[1]:5s} bg={r[2]} {r[3]:18s} {r[4][:60]} {r[5]}Z")
a = [r for r in rows if r[1] == "async"]
print(f"calls {len(rows)}; async {len(a)}; async held >60s {sum(r[0] > 60 for r in a)}; >150s {sum(r[0] > 150 for r in a)}; "
      f"total held {sum(r[0] for r in rows)/3600:.1f} h")
