#!/usr/bin/env -S python3 -u
"""A hand resolution belongs to the merge; a clean merge contributes nothing."""
import contextlib
import importlib.machinery
import importlib.util
import io
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_merge_own", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
sys.dont_write_bytecode = True
loader.exec_module(cl)
os.environ.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
fails = 0


def t(label, cond):
    global fails
    print(("  PASS " if cond else "  FAIL ") + label)
    fails += not cond


def git(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], check=check, capture_output=True, text=True).stdout.strip()


def commit(repo, path, contents):
    p = repo / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(contents)
    git(repo, "add", path)
    git(repo, "commit", "-qm", contents.strip())
    return git(repo, "rev-parse", "HEAD")


with tempfile.TemporaryDirectory(prefix="land-merge-own-") as d:
    root = Path(d)
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, "x/conflict", "base\n")
    git(repo, "checkout", "-qb", "side")
    commit(repo, "x/conflict", "side\n")
    git(repo, "branch", "landing")
    git(repo, "checkout", "-q", "main")
    commit(repo, "x/conflict", "main\n")
    git(repo, "branch", "integration")
    result = subprocess.run(["git", "-C", str(repo), "merge", "--no-ff", "side"], capture_output=True)
    assert result.returncode != 0
    merge = commit(repo, "x/conflict", "unique handmade resolution\n")
    manifest = root / "team.toml"
    manifest.write_text(f'repo = "{repo}"\nworktree_root = "{root / "team"}"\n'
                        '[[lanes]]\nname = "x"\npath = "x"\n[[lanes]]\nname = "y"\npath = "y"\n[land]\n')
    team = cl.Team(manifest)
    rec = {"wo": "resolution", "zone": "y", "tree": str(repo), "tip": merge}
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        try:
            cl.check_work_order(team, rec)
        except SystemExit:
            pass
    t("wall refuses the resolution's outside file", "outside zone y" in err.getvalue() and "x/conflict" in err.getvalue())
    row = {"wo": "resolution", "zone": "y", "feature": "f", "tip": merge, "recipient": "Kong", "seen": {}}
    request = cl.stage3_request(team, [row])
    command = request.split("feature f): ", 1)[1].split("; codeteam-land", 1)[0]
    output = subprocess.run(shlex.split(command), check=True, capture_output=True, text=True).stdout
    t("Stage 3 command prints the resolution", "+unique handmade resolution" in output)
    git(repo, "checkout", "-qb", "clean-side")
    commit(repo, "x/side", "side file\n")
    git(repo, "checkout", "-q", "main")
    commit(repo, "y/own", "own file\n")
    git(repo, "merge", "-q", "--no-ff", "--no-edit", "clean-side")
    clean = git(repo, "rev-parse", "HEAD")
    t("clean merge adds no review commit", clean not in cl.review_range(team, clean, []))
    t("clean merge adds no review files", cl.review_files(team, [clean]) == [])

print(f"{fails} failed" if fails else "all passed")
sys.exit(bool(fails))
