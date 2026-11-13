#!/usr/bin/env -S python3 -u
"""Stage 6's land-check starts each run without Python bytecode caches and its suite writes none (a
validation run's test once imported vendored code, left __pycache__ in the persistent land/validate tree, and the
next run's test of the vendored tree failed on it). Real git and the real land-check script, in a temp folder; HOME
points there too, for the script's logs."""
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_bytecode", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
sys.dont_write_bytecode = True
loader.exec_module(cl)

G = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]


def git(repo, *a):
    return subprocess.run([*G, "-C", str(repo), *a], capture_output=True, text=True, check=True).stdout.strip()


def test_caches_go_at_checkout_kept_folders_stay_and_the_suite_writes_none():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d).resolve()
        clone = d / "validate"
        subprocess.run(["git", "init", "-q", "-b", "main", str(clone)], check=True)
        (clone / ".gitignore").write_text("__pycache__/\n*.pyc\ncargo-target/\nweights/\n")
        (clone / "pkg").mkdir()
        (clone / "pkg" / "__init__.py").write_text("")
        (clone / "pkg" / "a.py").write_text("X = 1\n")
        git(clone, "add", "-A")
        git(clone, "commit", "-q", "-m", "base")
        h = git(clone, "rev-parse", "HEAD")
        # What an earlier run left: caches beside the code, a stray .pyc, an untracked file, and caches inside the
        # kept build folder and a LAND_KEEP input.
        for p in ("pkg/__pycache__/a.cpython-315.pyc", "__pycache__/top.pyc", "stray.pyc", "newfile",
                  "cargo-target/__pycache__/build.pyc", "weights/__pycache__/w.pyc", "weights/w.bin"):
            (clone / p).parent.mkdir(parents=True, exist_ok=True)
            (clone / p).write_text("x")
        (clone / ".git" / "land-check").write_text(cl.REMOTE_CHECK)
        seen = d / "seen.txt"
        suite = (f"python3 -c 'import pkg.a' && echo \"bytecode=$PYTHONDONTWRITEBYTECODE\" > {seen} && "
                 f"find . -path ./.git -prune -o \\( -name __pycache__ -o -name '*.pyc' \\) -print | sort >> {seen}")
        want = hashlib.sha1(b"").hexdigest()[:16]          # the fingerprint of `true`'s empty output
        env = dict(os.environ, HOME=str(d / "home"), LAND_KEEP="weights")
        env.pop("PYTHONDONTWRITEBYTECODE", None)
        r = subprocess.run(["sh", ".git/land-check", h, suite, "true", want], cwd=clone, capture_output=True,
                           text=True, env=env, timeout=120)
        result = json.loads(r.stdout.strip().splitlines()[-1])
        assert result["result"] == "pass", (result, r.stderr)
        lines = seen.read_text().split()
        assert lines[0] == "bytecode=1", lines
        assert sorted(lines[1:]) == ["./cargo-target/__pycache__", "./cargo-target/__pycache__/build.pyc",
                                     "./weights/__pycache__", "./weights/__pycache__/w.pyc"], lines
        assert not (clone / "newfile").exists()                # untracked files go, as before
        assert (clone / "weights" / "w.bin").exists()


if __name__ == "__main__":
    test_caches_go_at_checkout_kept_folders_stay_and_the_suite_writes_none()
    print("all passed")
