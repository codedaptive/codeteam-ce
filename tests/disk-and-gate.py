#!/usr/bin/env -S python3 -u
"""(A team once used 540 GB of disk, and a gate ran two hours and timed out.) The watchdog removes the
build output of idle work order trees when the disk runs low; the build queue gives the landing gate's jobs more
compile threads and the CPU ahead of leads' own builds. Throwaway folders only."""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HOME = Path(__file__).resolve().parents[1]


def load(name, f):
    ld = importlib.machinery.SourceFileLoader(name, str(HOME / "bin" / f))
    sp = importlib.util.spec_from_loader(name, ld)
    m = importlib.util.module_from_spec(sp)
    sys.modules[name] = m
    ld.exec_module(m)
    return m


wd = load("wd", "codeteam-watchdog")
wd.notify = lambda *a: None
bq = load("bq", "codeteam-buildq")
W = Path(tempfile.mkdtemp(prefix="disk-and-gate-"))
fails = 0


def t(label, cond, detail=""):
    global fails
    print(("  PASS " if cond else "  FAIL ") + label + ("" if cond else f"  [{detail}]"))
    fails += not cond


teams, q, root = W / "teams", W / "queue", W / "team-x"
teams.mkdir(); q.mkdir(); (root / "land" / "wo").mkdir(parents=True)
(teams / "x.toml").write_text(f'repo = "{W}"\nworktree_root = "{root}"\n')
old = time.time() - 7200


def tree(name, age, busy=False, landed=False):
    tr = root / "wo" / "z" / name
    tr.mkdir(parents=True)
    subprocess.run(f"git init -q && git -c user.email=t@t -c user.name=t commit -q --allow-empty -m i "
                   f"--date=@{int(age)}", shell=True, cwd=tr, env=dict(os.environ, GIT_COMMITTER_DATE=f"@{int(age)}"))
    (tr / "target" / "debug").mkdir(parents=True)
    (tr / "target" / "debug" / "big").write_text("x" * 1000)
    for p in [tr / ".git" / "index", tr / "target" / "debug" / "big", tr / "target" / "debug", tr / "target"]:
        if p.exists():
            os.utime(p, (age, age))
    rec = root / "land" / "wo" / (f"{name}.landed.json" if landed else f"{name}.json")
    rec.write_text(json.dumps({"wo": name, "tree": str(tr)}))
    if busy:
        (q / f"{name}.json").write_text(json.dumps({"state": "running", "worktree": str(tr)}))
    return tr


idle = tree("idle", old)
edited = tree("edited", old)
(edited / "notes.txt").write_text("a lead's edit, not built, not staged\n")
warm = tree("warm", old)
import fcntl
gd = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-dir"], cwd=warm, capture_output=True,
                    text=True).stdout.strip()
lockfd = os.open(os.path.join(gd, "codeteam-warm.lock"), os.O_RDWR | os.O_CREAT)
fcntl.flock(lockfd, fcntl.LOCK_EX)
stray = tree("stray", old)
(root / "land" / "wo" / "stray.json").unlink()      # a cancelled start: a tree with no record
recent = tree("recent", time.time())
busy = tree("busy", old, busy=True)
print("== the disk sweep")
t("nothing is removed while there is room",
  wd.sweep_disk(teams, q, min_gb=150, idle_s=1800, free=lambda: 500) == [] and (idle / "target").is_dir())
lines = wd.sweep_disk(teams, q, min_gb=150, idle_s=1800, free=lambda: 20)
t("an idle tree's build output goes when the disk is low", not (idle / "target").exists(), lines)
t("a tree touched within the idle time keeps it", (recent / "target").is_dir())
t("a tree with a build queued or running keeps it", (busy / "target").is_dir())
t("a tree with an uncommitted edit inside the idle time keeps it", (edited / "target").is_dir())
t("a tree whose warm build holds its lock keeps it", (warm / "target").is_dir())
t("a tree with no work order record is swept too", not (stray / "target").exists())
t("the tree itself and its git stay", (idle / ".git").exists())
time.sleep(1)
t("the trash is emptied in the background", not any((root / ".trash").iterdir()) if (root / ".trash").exists() else True,
  list((root / ".trash").iterdir()) if (root / ".trash").exists() else "")

print("== the gate's jobs come first")
c = W / "queue.toml"
c.write_text("budget = 34\n")
t("land_jobs defaults to 6", bq.load_config(c).land_jobs == 6)
c.write_text("budget = 34\nland_jobs = 9\n")
t("queue.toml can set it", bq.load_config(c).land_jobs == 9)
t("the gate runs at normal priority and leads' own builds last",
  bq.CLASS_NICE["land"] == 0 and bq.CLASS_NICE["dev"] == 10 and all(c in bq.CLASS_NICE for c in bq.CLASSES))

print(f"\n{'all passed' if not fails else f'{fails} failed'}  ({W})")
sys.exit(1 if fails else 0)
