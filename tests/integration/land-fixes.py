#!/usr/bin/env -S python3 -u
"""codeteam-land fixes of 2026-11-08 (problems 24, 26, 27, 28 in team-codeteam's problems report). A throwaway repo."""
import importlib.machinery
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

LAND = str(Path(__file__).resolve().parents[2] / "bin" / "codeteam-land")
loader = importlib.machinery.SourceFileLoader("cl", LAND)
spec = importlib.util.spec_from_loader("cl", loader)
cl = importlib.util.module_from_spec(spec)
loader.exec_module(cl)

W = Path(tempfile.mkdtemp(prefix="land-fixes-"))
REPO, ROOT = W / "repo", W / "team"
fails = 0


def t(label, cond, detail=""):
    global fails
    print(("  PASS " if cond else "  FAIL ") + label + ("" if cond else f"  [{detail}]"))
    fails += not cond


def sh(cmd, cwd=REPO):
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"setup failed: {cmd}\n{r.stdout}{r.stderr}")
    return r


REPO.mkdir()
for path, text in {"tests/test_a.py": "def test_a(): pass\n", "A/x.py": "x = 1\n",
                   "docs/reference/ARIA_MCP_SERVER_SPEC.md": "# spec\n"}.items():
    (REPO / path).parent.mkdir(parents=True, exist_ok=True)
    (REPO / path).write_text(text)
sh("git init -q -b main && git add -A && git -c user.email=t@t -c user.name=t commit -qm init && git branch integration")
(W / "team.toml").write_text(f'''repo = "{REPO}"
integration = "integration"
worktree_root = "{ROOT}"
[[lanes]]
name = "whole"
path = "."
[[lanes]]
name = "aria-mcp-server"
path = "A"
[land]
check = ""
gates = ""
notify = "sleep 20"
owner_notify = "sleep 20"
''')
team = cl.Team(str(W / "team.toml"), create=True)

print("== 28: a whole-repo zone (path \".\", no owns) runs no tests of its own")
t("zone_tests gives nothing for it", cl.zone_tests(team, str(REPO), "whole", "full") == [],
  cl.zone_tests(team, str(REPO), "whole", "full"))

print("== 24: a notice never blocks or kills the caller")
s = time.time()
team.notify("Kong", "NOTE", "a slow notice")
cl.tell_owner(team, "title", "body")
t("notify and tell_owner return at once though the notice takes 20 s", time.time() - s < 3, time.time() - s)

print("== 26: landing and the guard give a zone the same reference docs")
(ROOT / "team").mkdir(parents=True, exist_ok=True)
(ROOT / "team" / "team.json").write_text('{"lanes": {"whole": {"path": "."}, "aria-mcp-server": {"path": "A"}}}')
docs = cl.zone_docs(team, str(REPO), "aria-mcp-server")
t("ARIA_MCP_SERVER_SPEC.md is aria-mcp-server's (the guard's stem, not the zone name without dashes)",
  "docs/reference/ARIA_MCP_SERVER_SPEC.md" in docs, docs)

print("== 27: the idle check reads git, not the tree")
tree = W / "big"
sh(f"git worktree add -q -b wo/x {tree} integration")
(tree / ".gitignore").write_text("junk/\n")
for i in range(2000):
    (tree / "junk" / f"d{i % 50}").mkdir(parents=True, exist_ok=True)
    (tree / "junk" / f"d{i % 50}" / f"f{i}").write_text("x")
(ROOT / "land" / "wo").mkdir(parents=True, exist_ok=True)
import json
team.save_wo({"wo": "x", "zone": "aria-mcp-server", "tree": str(tree), "branch": "wo/x"})
calls = []
real_stat = Path.stat


def counting_stat(self, *a, **k):
    calls.append(self)
    return real_stat(self, *a, **k)


Path.stat = counting_stat
try:
    cl.clean_idle(team)
finally:
    Path.stat = real_stat
t("no file under an ignored folder is looked at", not any("junk" in str(p) for p in calls), len(calls))

if fails:
    print(f"\n{fails} failed  ({W} kept for a look)")
else:
    # 8 MB a run, left in the landing tool's TMPDIR every time: kept only on a failure.
    shutil.rmtree(W, ignore_errors=True)
    print("\nall passed")
sys.exit(1 if fails else 0)
