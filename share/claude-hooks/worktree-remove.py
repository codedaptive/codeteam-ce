#!/usr/bin/env python3
"""WorktreeRemove (global): remove a worktree made by worktree-create.py only when it
holds nothing (no uncommitted files, no commits beyond its starting commit). Anything
else stays: for team worktrees, codeteam's sweep removes it once its work is accepted."""
import json, os, subprocess, sys
from pathlib import Path
os.environ["PATH"] = "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:" + os.environ.get("PATH", "")
data = json.load(sys.stdin)
cands = [Path(v) for v in data.values() if isinstance(v, str) and v.startswith("/") and Path(v).is_dir()]
for path in cands:
    g = lambda *a: subprocess.run(["git", "-C", str(path), *a], capture_output=True, text=True).stdout.strip()
    if g("rev-parse", "--show-toplevel") != str(path.resolve()):
        continue
    common = Path(g("rev-parse", "--path-format=absolute", "--git-common-dir"))
    mark = common / "worktree-hook" / path.name
    start = mark.read_text().strip() if mark.exists() else ""
    if not start or g("status", "--porcelain") or g("rev-parse", "HEAD") != start:
        sys.exit(0)
    branch = g("rev-parse", "--abbrev-ref", "HEAD")
    subprocess.run(["git", "-C", str(common), "worktree", "remove", str(path)], capture_output=True)
    if branch == f"worktree-{path.name}":
        subprocess.run(["git", "-C", str(common), "branch", "-D", branch], capture_output=True)
    mark.unlink(missing_ok=True)
    break
