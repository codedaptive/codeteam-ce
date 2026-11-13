#!/usr/bin/env -S python3 -u
"""A tree that a dead land left on its landing set's merge goes back on its branch when the next land of it starts
(in a disk-full window the checkout in check_combined_members' finally once failed, and
the next land of one zone's work order was refused for its partner's docs file). Real git in a temp folder; the set's
merge is made by the tool's own merge_set_tips. The folder is removed on a pass and kept, named, on a failure."""
import importlib.machinery
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_put_back", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
sys.dont_write_bytecode = True
loader.exec_module(cl)

os.environ.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
W = Path(tempfile.mkdtemp(prefix="land-put-back-"))
fails = 0


def t(label, cond, detail=""):
    global fails
    print(("  PASS " if cond else "  FAIL ") + label + ("" if cond else f"  [{detail}]"))
    fails += not cond


def sh(cmd, cwd):
    return subprocess.run(cmd, shell=True, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def left_on_merge(name):
    """A work order tree on wo/z/w1 and a partner branch wo/orc/docs, combined in the tree as Stage 2 combines a set."""
    repo = W / name / "repo"
    repo.mkdir(parents=True)
    sh("git init -q -b main && echo a > a.txt && git add -A && git commit -qm init", repo)
    sh("git checkout -q -b wo/orc/docs && mkdir docs && echo doc > docs/lane.md && git add -A && git commit -qm docs"
       " && git checkout -q main && git branch wo/z/w1", repo)
    tree = W / name / "w1"
    sh(f"git worktree add -q {tree} wo/z/w1", repo)
    sh("echo code > code.txt && git add -A && git commit -qm w1", tree)
    rec = {"wo": "w1", "tree": str(tree), "branch": "wo/z/w1", "tip": sh("git rev-parse HEAD", tree)}
    partner = {"wo": "docs", "tip": sh("git rev-parse wo/orc/docs", repo)}
    cl.merge_set_tips(tree, [(rec, False), (partner, True)])
    return rec, tree


def put_back(rec):
    said = io.StringIO()
    with redirect_stdout(said):
        cl.put_back_set_merge(rec)
    return said.getvalue()


def on_branch(tree):
    r = subprocess.run("git symbolic-ref -q --short HEAD", shell=True, cwd=tree, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


print("== a dead land's set merge: put back on the branch")
rec, tree = left_on_merge("merge")
merge = sh("git rev-parse HEAD", tree)
t("the fixture is the state server's tree was in: detached on a merge of its tip and its partner's",
  on_branch(tree) is None and sh("git rev-parse HEAD^1", tree) == rec["tip"], sh("git log --oneline -3", tree))
said = put_back(rec)
t("the tree is back on its branch at its own tip", on_branch(tree) == "wo/z/w1" and sh("git rev-parse HEAD", tree)
  == rec["tip"], (on_branch(tree), sh("git rev-parse HEAD", tree)))
t("the partner's docs file is gone from the tree", not (tree / "docs" / "lane.md").exists())
t("it says what it did, naming the merge and the branch",
  f"w1: its tree was left on a landing set's merge ({merge[:10]})" in said and f"wo/z/w1 ({rec['tip'][:10]})" in said,
  said)

print("== a dead land killed between the detach and the merge: put back")
rec, tree = left_on_merge("detached-tip")
sh(f"git checkout -q --detach {rec['tip']}", tree)
put_back(rec)
t("detached at its own tip goes back on its branch", on_branch(tree) == "wo/z/w1", on_branch(tree))

print("== anything else is left as it is")
rec, tree = left_on_merge("tracked-change")
(tree / "code.txt").write_text("changed\n")
said = put_back(rec)
t("a tracked change: still detached, change kept, nothing said",
  on_branch(tree) is None and (tree / "code.txt").read_text() == "changed\n" and said == "", (on_branch(tree), said))

rec, tree = left_on_merge("commit-on-top")
sh("echo more > more.txt && git add -A && git commit -qm 'work on the detached head'", tree)
top = sh("git rev-parse HEAD", tree)
said = put_back(rec)
t("a commit that is not a merge on top: still detached on it", on_branch(tree) is None and
  sh("git rev-parse HEAD", tree) == top and said == "", (on_branch(tree), said))

rec, tree = left_on_merge("branch-moved")
sh("git branch -f wo/z/w1 HEAD^2", tree)            # the branch no longer under the merge's first parent
said = put_back(rec)
t("a branch that moved since: still detached", on_branch(tree) is None and said == "", (on_branch(tree), said))

rec, tree = left_on_merge("on-branch")
sh("git checkout -q wo/z/w1", tree)
said = put_back(rec)
t("a tree on its branch: nothing done, nothing said", on_branch(tree) == "wo/z/w1" and said == "", said)

if fails:
    print(f"\n{fails} failed  ({W} kept for a look)")
else:
    shutil.rmtree(W, ignore_errors=True)
    print("\nall passed")
sys.exit(1 if fails else 0)
