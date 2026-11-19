#!/usr/bin/env python3
"""Idle and landed work trees are cleaned only when nobody is inside."""
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOME = Path(__file__).resolve().parents[2]
LAND = HOME / "bin" / "codeteam-land"
FAILS = 0


def check(label, condition, detail=""):
    global FAILS
    print(("  PASS " if condition else "  FAIL ") + label + ("" if condition else f"  [{detail}]"))
    FAILS += not condition


def run(args, cwd, env):
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{args}: {result.stdout}{result.stderr}")
    return result


def setup(root, idle_hours=None):
    repo = root / "repo"
    repo.mkdir()
    (repo / "A").mkdir()
    (repo / "A" / "x").write_text("initial\n")
    (repo / ".gitignore").write_text(".codegraph/\ntarget/\n")
    env = {key: value for key, value in os.environ.items() if not key.startswith("CODETEAM_")}
    queue = root / "queue"
    queue.mkdir()
    calls = root / "calls"
    codegraph = root / "codegraph"
    codegraph.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$CG_CALLS"\n')
    codegraph.chmod(0o755)
    env.update(CODETEAM_CODEGRAPH=str(codegraph), CODETEAM_QUEUE_DIR=str(queue), CG_CALLS=str(calls))
    run(["git", "init", "-q", "-b", "main"], repo, env)
    run(["git", "add", "-A"], repo, env)
    run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "initial"], repo, env)
    run(["git", "branch", "integration"], repo, env)
    team = root / "team.toml"
    team.write_text(f'''repo = "{repo}"
integration = "integration"
worktree_root = "{root / "team"}"
[[lanes]]
name = "A"
path = "A"
[land]
check = ""
gates = ""
notify = "true"
''' + (f"idle_hours = {idle_hours}\n" if idle_hours is not None else ""))
    return repo, team, env, calls


def cut(root, repo, team, env, name, age_minutes):
    run([str(LAND), str(team), "wo-cut", "A", name], repo, env)
    tree = root / "team" / "wo" / "A" / name
    date = (datetime.now(timezone.utc) - timedelta(minutes=age_minutes)).isoformat()
    commit_env = dict(env, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "--allow-empty", "-qm", "activity"],
        tree, commit_env)
    (tree / ".codegraph").mkdir()
    (tree / ".codegraph" / "index").write_text("index")
    return tree


def recorded(calls):
    return calls.read_text().splitlines() if calls.exists() else []


def clean(repo, team, env):
    return run([str(LAND), str(team), "clean-idle"], repo, env).stdout


def default_limit(root):
    repo, team, env, calls = setup(root)
    old = cut(root, repo, team, env, "old", 61)
    recent = cut(root, repo, team, env, "recent", 59)
    output = clean(repo, team, env)
    check("default one-hour limit cleans 61-minute tree", not (old / ".codegraph").exists(), output)
    check("default one-hour limit keeps 59-minute tree", (recent / ".codegraph").exists(), output)
    check("default cleanup unregisters only old tree", recorded(calls) == [f"project remove {old.resolve()}"], recorded(calls))
    check("default cleanup prints per-tree freed MB", bool(re.search(
        rf"clean_idle: old {re.escape(str(old))} freed \d+ MB", output)), output)


def landed_once(root):
    repo, team, env, calls = setup(root)
    tree = cut(root, repo, team, env, "landed", 0)
    (tree / "target").mkdir()
    (tree / "target" / "output").write_text("build")
    record = root / "team" / "land" / "wo" / "landed.json"
    landed = record.with_name("landed.landed.json")
    record.rename(landed)
    output = clean(repo, team, env)
    check("fresh landed tree removes index and build output", not (tree / ".codegraph").exists()
          and not (tree / "target").exists(), output)
    check("landed cleanup unregisters physical tree once", recorded(calls) == [f"project remove {tree.resolve()}"], recorded(calls))
    check("landed record receives landed_cleaned", bool(json.loads(landed.read_text()).get("landed_cleaned")))
    check("landed cleanup does not recreate open record", not record.exists())
    check("landed cleanup prints per-tree freed MB", bool(re.search(
        rf"clean_idle: landed {re.escape(str(tree))} freed \d+ MB", output)), output)
    (tree / ".codegraph").mkdir(exist_ok=True)
    clean(repo, team, env)
    check("second landed pass leaves recreated index", (tree / ".codegraph").exists())
    check("second landed pass does not unregister again", recorded(calls) == [f"project remove {tree.resolve()}"], recorded(calls))
    check("second landed pass does not recreate open record", not record.exists())


def live_process(root):
    repo, team, env, calls = setup(root, idle_hours=0.5)
    tree = cut(root, repo, team, env, "occupied", 61)
    sleeper = subprocess.Popen(["sleep", "60"], cwd=tree, env=env)
    try:
        output = clean(repo, team, env)
        check("idle tree with a process inside keeps its index", (tree / ".codegraph").exists(), output)
        check("idle tree with a process inside is not unregistered", recorded(calls) == [], recorded(calls))
    finally:
        sleeper.terminate()
        sleeper.wait()


with tempfile.TemporaryDirectory(prefix="land-clean-idle-landed-") as tmp:
    base = Path(tmp).resolve()
    for name, case in (("default", default_limit), ("landed", landed_once), ("occupied", live_process)):
        root = base / name
        root.mkdir()
        case(root)

print(f"\n{FAILS} failed" if FAILS else "\nall passed")
sys.exit(1 if FAILS else 0)
