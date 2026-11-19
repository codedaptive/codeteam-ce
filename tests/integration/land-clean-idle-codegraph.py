#!/usr/bin/env python3
"""Idle cleanup unregisters and removes indexes, and the command reports freed bytes."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HOME = Path(__file__).resolve().parents[2]
LAND = str(HOME / "bin" / "codeteam-land")
W = Path(tempfile.mkdtemp(prefix="land-clean-idle-"))
REPO, ROOT = W / "repo", W / "team"
CG, CALLS = W / "codegraph", W / "calls"
CG.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$CG_CALLS"\n')
CG.chmod(0o755)
for key in tuple(os.environ):
    if key.startswith("CODETEAM_"):
        del os.environ[key]
os.environ["CODETEAM_CODEGRAPH"] = str(CG)
os.environ["CG_CALLS"] = str(CALLS)
os.environ["CODETEAM_SESSION"] = "orc"
loader = importlib.machinery.SourceFileLoader("cl", LAND)
spec = importlib.util.spec_from_loader("cl", loader)
cl = importlib.util.module_from_spec(spec)
sys.modules["cl"] = cl
loader.exec_module(cl)
fails = 0


def t(label, cond, detail=""):
    global fails
    print(("  PASS " if cond else "  FAIL ") + label + ("" if cond else f"  [{detail}]"))
    fails += not cond


def run(*args, cwd=REPO):
    result = subprocess.run(args, cwd=cwd, env=os.environ.copy(), capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(f"setup failed: {args}\n{result.stdout}{result.stderr}")
    return result


def land(*args):
    return subprocess.run([LAND, str(W / "team.toml"), *args], env=os.environ.copy(), capture_output=True, text=True)


def calls():
    return CALLS.read_text().splitlines() if CALLS.exists() else []


def index(tree, size):
    (tree / ".codegraph").mkdir(exist_ok=True)
    (tree / ".codegraph" / "index").write_bytes(b"x" * size)


def clean(team):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        freed = cl.clean_idle(team)
    return freed, out.getvalue()


REPO.mkdir()
(REPO / "A").mkdir()
(REPO / "A" / "x").write_text("initial\n")
(REPO / ".gitignore").write_text(".codegraph/\n")
run("git", "init", "-q", "-b", "main")
run("git", "add", "-A")
run("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "initial")
run("git", "branch", "integration")
(W / "team.toml").write_text(f'''repo = "{REPO}"
integration = "integration"
worktree_root = "{ROOT}"
[[lanes]]
name = "A"
path = "A"
[land]
idle_hours = 0
check = ""
gates = ""
notify = "true"
''')
team = cl.Team(str(W / "team.toml"), create=True)
result = land("wo-cut", "A", "idle-one")
if result.returncode:
    raise SystemExit(f"wo-cut failed: {result.stdout}{result.stderr}")
tree = ROOT / "wo" / "A" / "idle-one"
record = ROOT / "land" / "wo" / "idle-one.json"
index(tree, 200 * 1024)
freed, output = clean(team)
mark = json.loads(record.read_text()).get("cleaned")
t("codegraph-only idle tree is cleaned", not (tree / ".codegraph").exists())
t("cleanup unregisters exactly this physical tree", calls() == [f"project remove {tree.resolve()}"], calls())
t("cleanup records a mark", bool(mark), mark)
t("cleanup logs work order, path and freed", "clean_idle:" in output and "idle-one" in output
  and str(tree) in output and "freed" in output, output)
t("cleanup returns at least the index file size", isinstance(freed, int) and freed >= 200 * 1024, freed)

index(tree, 200 * 1024)
freed_again, output_again = clean(team)
t("unchanged idle tree keeps its recreated index and mark", (tree / ".codegraph").exists()
  and bool(mark) and json.loads(record.read_text()).get("cleaned") == mark)
t("unchanged idle tree is not unregistered again", calls() == [f"project remove {tree.resolve()}"], calls())
t("unchanged idle tree reports no bytes or clean line", freed_again == 0 and "clean_idle:" not in output_again,
  (freed_again, output_again))

rec = json.loads(record.read_text())
rec["cleaned"] = "2000-01-01T00:00:00+00:00"
record.write_text(json.dumps(rec))
(tree / "A" / "x").write_text("used again\n")
run("git", "add", "A/x", cwd=tree)
run("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "used again", cwd=tree)
freed_used, output_used = clean(team)
t("a commit after the mark makes the tree cleanable again", not (tree / ".codegraph").exists()
  and isinstance(freed_used, int) and freed_used >= 200 * 1024, (freed_used, output_used))
t("used tree is unregistered a second time", calls() == [f"project remove {tree.resolve()}"] * 2, calls())
t("used tree receives a new mark", json.loads(record.read_text()).get("cleaned") != "2000-01-01T00:00:00+00:00")

result = land("wo-cut", "A", "idle-cli")
if result.returncode:
    raise SystemExit(f"second wo-cut failed: {result.stdout}{result.stderr}")
cli_tree = ROOT / "wo" / "A" / "idle-cli"
index(cli_tree, 2 * 1024 * 1024)
result = land("clean-idle")
t("clean-idle exits successfully", result.returncode == 0, result.stderr)
t("clean-idle removes the fresh tree index", not (cli_tree / ".codegraph").exists())
lines = result.stdout.splitlines()
t("clean-idle prints the per-tree line before its total", any("clean_idle:" in line and "idle-cli" in line
  and str(cli_tree) in line and "freed" in line for line in lines[:-1]), result.stdout)
t("clean-idle ends with the integer MB total", bool(lines) and bool(re.fullmatch(r"clean-idle: freed 2 MB", lines[-1])),
  result.stdout)

if fails:
    print(f"\n{fails} failed  ({W} kept for a look)")
else:
    shutil.rmtree(W)
    print("\nall passed")
sys.exit(1 if fails else 0)
