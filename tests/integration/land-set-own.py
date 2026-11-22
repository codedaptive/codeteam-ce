#!/usr/bin/env -S python3 -u
"""Set members are walled by their own commits, including ancestor members."""
import contextlib
import importlib.machinery
import importlib.util
import inspect
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_set_own", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
sys.dont_write_bytecode = True
loader.exec_module(cl)
os.environ.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
fails = 0


def t(label, cond):
    global fails
    print(("  PASS " if cond else "  FAIL ") + label)
    fails += not cond


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def commit(repo, name):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(name)
    git(repo, "add", name)
    git(repo, "commit", "-qm", name)
    return git(repo, "rev-parse", "HEAD")


def checked(team, rec, others):
    if len(inspect.signature(cl.check_work_order).parameters) < 3:
        return None
    try:
        return cl.check_work_order(team, rec, others)
    except SystemExit:
        return None


with tempfile.TemporaryDirectory(prefix="land-set-own-") as d:
    root = Path(d)
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, "base")
    git(repo, "branch", "landing")
    git(repo, "branch", "integration")
    a, b = root / "a", root / "b"
    git(repo, "worktree", "add", "-qb", "a", str(a), "main")
    git(repo, "worktree", "add", "-qb", "b", str(b), "main")
    ahead = commit(a, "x/a")
    commit(b, "y/b")
    git(b, "merge", "-q", "--no-ff", "--no-edit", "a")
    bhead = git(b, "rev-parse", "HEAD")
    manifest = root / "team.toml"
    manifest.write_text(f'repo = "{repo}"\nworktree_root = "{root / "team"}"\n'
                        '[[lanes]]\nname = "x"\npath = "x"\n[[lanes]]\nname = "y"\npath = "y"\n[land]\n')
    team = cl.Team(manifest)
    ra = {"wo": "a", "zone": "x", "tree": str(a), "tip": ahead}
    rb = {"wo": "b", "zone": "y", "tree": str(b), "tip": bhead}
    t("B excludes A's files in a set", checked(team, rb, [ahead]) == ["y/b"])
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        try:
            cl.check_work_order(team, rb)
        except SystemExit:
            pass
    t("B alone is refused for A's outside file", "outside zone y" in err.getvalue() and "x/a" in err.getvalue())
    files = getattr(cl, "set_member_files", lambda *args: None)
    t("set member files omit A", files(team, rb, [ahead]) == ["y/b"])
    t("lone member files retain the net list", files(team, rb, []) == ["x/a", "y/b"])
    heads = getattr(cl, "other_member_heads", lambda *args: None)
    t("ancestor A skips descendant B", heads([ra, rb], ra) == [])
    t("ancestor A still passes its own wall", checked(team, ra, []) == ["x/a"])
    t("descendant B excludes ancestor A", heads([ra, rb], rb) == [ahead] and checked(team, rb, [ahead]) == ["y/b"])

    a2, b2 = root / "a2", root / "b2"
    git(repo, "worktree", "add", "-qb", "a2", str(a2), "main")
    git(repo, "worktree", "add", "-qb", "b2", str(b2), "main")
    commit(a2, "x/a2")
    b2head = commit(b2, "y/b2")
    git(a2, "merge", "-q", "--no-ff", "--no-edit", "b2")
    ra2 = {"wo": "a2", "zone": "x", "tree": str(a2), "tip": git(a2, "rev-parse", "HEAD")}
    rb2 = {"wo": "b2", "zone": "y", "tree": str(b2), "tip": b2head}
    t("ancestor B skips descendant A", heads([ra2, rb2], rb2) == [])
    t("ancestor B passes without nothing-to-land", checked(team, rb2, []) == ["y/b2"])
    t("descendant A excludes B's files", checked(team, ra2, [b2head]) == ["x/a2"])

print(f"{fails} failed" if fails else "all passed")
sys.exit(bool(fails))
