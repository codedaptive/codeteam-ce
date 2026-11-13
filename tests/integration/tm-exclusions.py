"""Time Machine exclusions for build output. Real git in a temp folder. No check reaches the
real Time Machine (zone/docs/TESTING.md): a recorder stands in for the API call (`mark`), and a stub tmutil first on PATH
records its argv for the fallback.

A team root holds a work order tree with build output at its root and beside its package manifests, a lane worktree,
land/itest (a worktree) and land/validate (a clone): the land trees are marked whole, every build folder that exists is
marked, nothing is created, and a worktree of the same repo outside the team root is left alone. A folder the API cannot
mark goes to tmutil.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
G = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]


def load(refuse=()):
    """The module, with macOS assumed and the API call replaced by a recorder that refuses the names in `refuse`."""
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("codeteam_tm", ROOT / "share" / "codeteam_tm.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.platform = SimpleNamespace(system=lambda: "Darwin")
    module.marked = []

    def mark(paths):
        module.marked.extend(paths)
        return [p for p in paths if Path(p).name in refuse]
    module.mark = mark
    return module


def git(repo, *a):
    return subprocess.run([*G, "-C", str(repo), *a], capture_output=True, text=True, check=True).stdout.strip()


def build(d):
    repo, root = d / "repo", d / "team"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    for name in ("Cargo.toml", "kits/A/Package.swift", "kits/B/Package.swift", "web/package.json", "README.md"):
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text("x\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    wo = root / "wo" / "A" / "w1"
    lane = root / "workcrews" / "A" / "main"
    for tree in (wo, lane):
        tree.parent.mkdir(parents=True, exist_ok=True)
        git(repo, "worktree", "add", "-q", "--detach", str(tree), "main")
    git(repo, "worktree", "add", "-q", "--detach", str(root / "land" / "itest"), "main")
    git(repo, "worktree", "add", "-q", "--detach", str(d / "elsewhere"), "main")
    subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", str(repo), str(root / "land" / "validate")],
                   check=True)
    built = [wo / "DerivedData", wo / "cargo-target", wo / "target", wo / ".codegraph", wo / "kits" / "A" / ".build",
             wo / "web" / "node_modules", lane / "target"]
    for p in built + [wo / "docs", d / "elsewhere" / "target"]:
        p.mkdir(parents=True)
    return repo, root, wo, built


def stub(d):
    bin_ = d / "stub"
    bin_.mkdir()
    log = d / "tmutil.log"
    (bin_ / "tmutil").write_text(f"#!/bin/sh\n[ \"$1\" = addexclusion ] || exit 9\nshift\n"
                                 f"for a in \"$@\"; do echo \"$a\" >> '{log}'; done\nexit 0\n")
    (bin_ / "tmutil").chmod(0o755)
    os.environ["PATH"] = f"{bin_}:{os.environ['PATH']}"
    return log


def test_land_trees_whole_and_existing_build_output_marked_nothing_created():
    tm = load()
    path = os.environ["PATH"]
    with tempfile.TemporaryDirectory() as d:
        d = Path(d).resolve()
        repo, root, wo, built = build(d)
        log = stub(d)
        try:
            n = tm.exclude_team(root, repo)
        finally:
            os.environ["PATH"] = path
        want = {str(p) for p in built} | {str(root / "land" / "itest"), str(root / "land" / "validate")}
        assert set(tm.marked) == want, (set(tm.marked) ^ want)
        assert n == len(tm.marked) == len(want)
        assert not log.exists()                             # the API marked them all: tmutil is never run
        # nothing pre-created: kits/B has no .build until something builds it
        assert not (wo / "kits" / "B" / ".build").exists()
        assert not (root / "land" / "landing-tree").exists()


def test_a_wo_tree_marks_only_the_build_output_it_has_and_tmutil_takes_what_the_api_refused():
    tm = load(refuse={"DerivedData", "node_modules"})
    path = os.environ["PATH"]
    with tempfile.TemporaryDirectory() as d:
        d = Path(d).resolve()
        repo, root, wo, built = build(d)
        log = stub(d)
        try:
            assert tm.exclude(tm.build_dirs(wo)) == 6
            assert tm.exclude([]) == 0
        finally:
            os.environ["PATH"] = path
        assert set(tm.marked) == {str(p) for p in built if p.is_relative_to(wo)}
        assert set(log.read_text().split()) == {str(wo / "DerivedData"), str(wo / "web" / "node_modules")}


if __name__ == "__main__":
    test_land_trees_whole_and_existing_build_output_marked_nothing_created()
    test_a_wo_tree_marks_only_the_build_output_it_has_and_tmutil_takes_what_the_api_refused()
    print("all passed")
