#!/usr/bin/env -S python3 -u
"""The recheck tree comes back when its folder was deleted while git still lists it (once
land/itest was removed by hand, every `git worktree add` then failed with "missing but already registered worktree",
and the recheck row was completed with no tests run). Real git in a temp folder; Time Machine exclusion is faked."""
import importlib.machinery
import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_itest_readd", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
sys.dont_write_bytecode = True
loader.exec_module(cl)

G = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]


def git(repo, *a):
    return subprocess.run([*G, "-C", str(repo), *a], capture_output=True, text=True, check=True).stdout.strip()


def test_a_deleted_but_registered_itest_tree_is_checked_out_again():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d).resolve()
        repo = d / "repo"
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        (repo / "f").write_text("1\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "one")
        first = git(repo, "rev-parse", "HEAD")
        (repo / "f").write_text("2\n")
        git(repo, "commit", "-q", "-am", "two")
        M = git(repo, "rev-parse", "HEAD")
        manifest = d / "sample.toml"
        manifest.write_text(f'repo = "{repo}"\nworktree_root = "{d / "team"}"\n[land]\nseed_index = false\n')
        team = cl.Team(manifest)
        tree = team.dir / "itest"
        git(repo, "worktree", "add", "-q", "--detach", str(tree), first)
        shutil.rmtree(tree)                                  # deleted by hand; git still lists it
        plain = subprocess.run([*G, "-C", str(repo), "worktree", "add", "--detach", str(tree), M],
                               capture_output=True, text=True)
        assert plain.returncode and "already registered worktree" in plain.stderr, plain.stderr
        with patch.object(cl.codeteam_tm, "exclude"):
            assert cl.itest_checkout(team, M) == tree
        assert git(tree, "rev-parse", "HEAD") == M
        assert (tree / "f").read_text() == "2\n"


if __name__ == "__main__":
    test_a_deleted_but_registered_itest_tree_is_checked_out_again()
    print("all passed")
