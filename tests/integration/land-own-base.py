#!/usr/bin/env -S python3 -u
"""A work order's own changes are measured from what its tree holds of landed work, not from today's integration.
A throwaway repo stands for a team: a tree cut before the v5.4 move
whose landing was later rewritten, a fix tree that merged landing, and an ordinary tree."""
import importlib.machinery
import importlib.util
import os
import shlex
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_own_base", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
loader.exec_module(cl)

ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
           CODETEAM_LAND_TOOL="1")


def sh(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, env=ENV, check=True, capture_output=True, text=True).stdout.strip()


def commit(cwd, path, text, msg):
    f = Path(cwd) / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
    sh(cwd, "add", path)
    sh(cwd, "commit", "-qm", msg)
    return sh(cwd, "rev-parse", "HEAD")


def setup(tmp):
    repo = tmp / "repo"
    repo.mkdir()
    sh(repo, "init", "-q", "-b", "main")
    base = commit(repo, "A/a", "0", "base")
    manifest = tmp / "t.toml"
    manifest.write_text(f'repo = "{repo}"\nworktree_root = "{tmp / "team"}"\n'
                        '[[lanes]]\nname = "A"\npath = "A"\n[[lanes]]\nname = "B"\npath = "B"\n[land]\n')
    return repo, base, cl.Team(manifest)


def test_a_tree_cut_before_the_move_counts_only_its_own_commit_after_landing_is_rewritten():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        repo, base, team = setup(tmp)
        sh(repo, "checkout", "-q", "-b", "integration")
        for n in range(3):
            commit(repo, f"B/b{n}", str(n), f"landed {n}\n\nRequest: x")
        old_tip = sh(repo, "rev-parse", "HEAD")
        tree = tmp / "tree"
        sh(repo, "worktree", "add", "-q", "-b", "wo/A/w", str(tree), old_tip)
        own = commit(tree, "A/a", "1", "own work")
        sh(repo, "checkout", "-q", "main")
        sh(repo, "branch", "landing", old_tip)                      # the move: landing is the old integration
        sh(repo, "branch", "-f", "integration", base)               # integration is base
        sh(repo, "update-ref", "refs/archive/landing-before-rewrite", old_tip)
        sh(repo, "checkout", "-q", "--detach", base)                 # the rewrite: same trees, new hashes
        for n in range(3):
            commit(repo, f"B/b{n}", str(n), f"landed {n}")
        sh(repo, "branch", "-f", "landing", "HEAD")
        sh(repo, "checkout", "-q", "main")
        assert cl.own_base(team, tree) == old_tip
        assert cl.review_range(team, own, []) == [own]
        assert cl.changed_files(tree, cl.own_base(team, tree)) == ["A/a"]
        # The command the reviewer is sent lists the same commits as the recorded range.
        row = {"wo": "wo/A/w", "zone": "A", "feature": "f", "tip": own, "recipient": "Kong", "seen": {}}
        text = cl.stage3_request(team, [row])
        command = text.split("feature f): ", 1)[1].split("; codeteam-land", 1)[0]
        assert "refs/archive/landing-before-rewrite" in command, command
        listed = subprocess.run(shlex.split(command.replace(" -p ", " --format=%H ", 1)), env=ENV, check=True,
                                capture_output=True, text=True).stdout.split()
        assert listed == [own], listed


def test_a_fix_tree_that_merged_landing_counts_only_its_fix():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        repo, base, team = setup(tmp)
        sh(repo, "branch", "integration", base)
        sh(repo, "checkout", "-q", "-b", "landing")
        commit(repo, "B/broke", "x", "landed, breaks a test")
        landing_tip = sh(repo, "rev-parse", "HEAD")
        sh(repo, "checkout", "-q", "main")
        tree = tmp / "fix"
        sh(repo, "worktree", "add", "-q", "-b", "wo/A/fix", str(tree), "integration")
        sh(tree, "merge", "-q", "--no-edit", "landing")
        fix = commit(tree, "A/fix", "y", "the fix")
        assert cl.own_base(team, tree) == landing_tip
        assert cl.review_range(team, fix, []) == [fix]
        assert cl.changed_files(tree, cl.own_base(team, tree)) == ["A/fix"]


def test_an_ordinary_tree_is_measured_from_integration():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        repo, base, team = setup(tmp)
        sh(repo, "branch", "integration", base)
        sh(repo, "branch", "landing", base)
        tree = tmp / "w"
        sh(repo, "worktree", "add", "-q", "-b", "wo/A/w", str(tree), "integration")
        own = commit(tree, "A/a", "2", "own")
        assert cl.own_base(team, tree) == base
        assert cl.review_range(team, own, []) == [own]


if __name__ == "__main__":
    import inspect
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn()
                print(f"  PASS {name}")
            except Exception as ex:          # report every case, then fail once
                failed += 1
                print(f"  FAIL {name}: {type(ex).__name__}: {ex}")
    print("all passed" if not failed else f"{failed} failed")
    raise SystemExit(1 if failed else 0)
