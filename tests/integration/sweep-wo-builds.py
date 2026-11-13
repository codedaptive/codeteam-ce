#!/usr/bin/env -S python3 -u
"""The hourly sweep clears build output in a v5.4 work order tree (<worktree_root>/wo/<zone>/<wo>) idle for
REQUEST_BUILD_IDLE_HOURS, and keeps it in a work order tree in use, while the tree and its branch stay
(2026-11-11: 66 work order trees held 189 GB and the sweep skipped them). Real git in a temp folder."""
import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
G = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]


def load():
    sys.dont_write_bytecode = True
    loader = importlib.machinery.SourceFileLoader("codeteam_sweep_builds", str(ROOT / "bin" / "codeteam"))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


def git(repo, *a, env=None):
    return subprocess.run([*G, "-C", str(repo), *a], capture_output=True, text=True, check=True,
                          env=dict(os.environ, **(env or {}))).stdout


def age(path, seconds):
    old = time.time() - seconds
    for p in [path, *path.rglob("*")]:
        os.utime(p, (old, old), follow_symlinks=False)


def test_idle_work_order_build_output_goes_and_busy_stays():
    ct = load()
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        repo, root = d / "repo", d / "team"
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        old = str(int(time.time() - 5 * 3600))
        git(repo, "commit", "-q", "--allow-empty", "-m", "base",
            env={"GIT_COMMITTER_DATE": old, "GIT_AUTHOR_DATE": old})
        trees = {}
        for name in ("idle", "busy"):
            tree = root / "wo" / "A" / name
            git(repo, "worktree", "add", "-q", "-b", f"wo/A/{name}", str(tree), "main")
            (tree / ".build" / "debug").mkdir(parents=True)
            (tree / ".build" / "debug" / "obj.o").write_text("x" * 1000)
            trees[name] = tree
        age(trees["idle"] / ".build", 3 * 3600)
        os.utime(trees["idle"] / ".git", (time.time() - 3 * 3600,) * 2)
        os.utime(trees["busy"] / ".git", (time.time() - 3 * 3600,) * 2)      # the build folder is fresh: in use
        manifest = d / "t.toml"
        manifest.write_text(f'product = "p"\nrepo = "{repo}"\nbase = "main"\nworktree_root = "{root}"\n')
        t = ct.Team(str(manifest))
        ct._CWDS = []
        ct.sweep_builds_and_units(t, {"lanes": {}}, dry_run=False, builds_only=True)
        assert not (trees["idle"] / ".build").exists(), "idle work order tree kept its build output"
        assert (trees["busy"] / ".build" / "debug" / "obj.o").exists(), "a work order tree in use lost its build output"
        assert trees["idle"].is_dir() and "wo/A/idle" in git(repo, "branch", "--list", "wo/A/idle")


if __name__ == "__main__":
    test_idle_work_order_build_output_goes_and_busy_stays()
    print("  PASS test_idle_work_order_build_output_goes_and_busy_stays")
