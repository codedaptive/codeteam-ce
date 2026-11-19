#!/usr/bin/env -S python3 -u
"""Criss-cross landed histories are excluded from a work order's changes."""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_criss_cross", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
loader.exec_module(cl)
ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_AUTHOR_DATE="2001-01-01T00:00:00Z",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t", GIT_COMMITTER_DATE="2001-01-01T00:00:00Z",
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
    base = commit(repo, "A/base", "base\n", "base")
    manifest = tmp / "t.toml"
    manifest.write_text(f'repo = "{repo}"\nworktree_root = "{tmp / "team"}"\n'
                        '[[lanes]]\nname = "A"\npath = "A"\n[[lanes]]\nname = "B"\npath = "B"\n[land]\n')
    return repo, base, cl.Team(manifest)


def criss_cross(tmp, conflict=False):
    repo, base, team = setup(tmp)
    if conflict:
        base = commit(repo, "A/conflict", "base\n", "conflict base")
    sh(repo, "checkout", "-q", "-b", "integration")
    i = commit(repo, "A/conflict" if conflict else "A/landed_i.rs",
               "integration\n" if conflict else "pub fn landed_i() {}\n", "integration I")
    sh(repo, "checkout", "-q", "-b", "landing", base)
    m = commit(repo, "A/conflict" if conflict else "A/landed_m.rs",
               "landing\n" if conflict else "pub fn landed_m() {}\n", "landing M")
    tree = tmp / "tree"
    sh(repo, "worktree", "add", "-q", "-b", "wo/A/w", str(tree), i)
    for cwd, other in ((tree, m), (repo, i)):
        result = subprocess.run(["git", "merge", "--no-ff", "--no-edit", other], cwd=cwd, env=ENV,
                                capture_output=True, text=True)
        if conflict:
            assert result.returncode != 0, result.stdout
            (cwd / "A/conflict").write_text("resolved\n")
            sh(cwd, "add", "A/conflict")
            sh(cwd, "commit", "-qm", "resolve merge")
        else:
            assert result.returncode == 0, result.stderr
    commit(tree, "A/own", "own\n", "own")
    return repo, tree, team, i, m


def merged_base_for(team, tree):
    sys.path.insert(0, str(ROOT / "share"))
    from codeteam_merged_base import merged_base
    def git(*args, env=None):
        return subprocess.run(["git", *args], cwd=tree, env=env or ENV, capture_output=True, text=True)
    return merged_base(git, "HEAD", cl.landed_refs(team, tree))


def test_criss_cross_excludes_both_landed_sides():
    with tempfile.TemporaryDirectory() as d:
        repo, tree, team, i, m = criss_cross(Path(d))
        base = cl.own_base(team, tree)
        files = sh(tree, "diff", "--name-only", base, "HEAD").splitlines()
        assert files == ["A/own"], files
        assert cl.changed_files(tree, base) == ["A/own"]
        sh(tree, "merge-base", "--is-ancestor", i, base)
        sh(tree, "merge-base", "--is-ancestor", m, base)


def test_interface_changes_excludes_landed_declarations_but_keeps_own():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        repo, tree, team, i, m = criss_cross(tmp)
        commit(tree, "A/own.rs", "pub fn own() {}\n", "own function")
        blast = {"changed": [{"path": f"A/{name}.rs", "hunks": [{"lines": [{"n": 1, "sign": "+"}]}]}
                             for name in ("landed_i", "landed_m", "own")],
                 "seeds": [{"kind": "function", "name": name, "path": f"A/{name}.rs", "span": "L1-L1"}
                           for name in ("landed_i", "landed_m", "own")]}
        cg = tmp / "fake-codegraph"
        callers = {"callers": [{"path": "B/caller.rs"}], "total": 1, "limit": 10000, "truncated": False,
                   "definitions": [{"callers": [{"path": "B/caller.rs"}], "total": 1,
                                    "limit": 10000, "truncated": False}]}
        cg.write_text("#!/bin/sh\nif [ \"$1\" = blast ]; then\n  printf '%s\\n' " +
                      "'" + json.dumps(blast) + "'\nelse\n  printf '%s\\n' '" + json.dumps(callers) + "'\nfi\n")
        cg.chmod(0o755)
        previous = cl.CG
        cl.CG = str(cg)
        try:
            found = cl.interface_changes(team, {"tree": str(tree), "zone": "A"})
        finally:
            cl.CG = previous
        assert found == {"own (A/own.rs:L1-L1)": ["B"]}, found


def test_api_delta_excludes_landed_declarations():
    with tempfile.TemporaryDirectory() as d:
        repo, tree, team, i, m = criss_cross(Path(d))
        commit(tree, "A/own.rs", "pub fn own() {}\n", "own function")
        delta = cl.api_delta(team, {"tree": str(tree), "zone": "A"})
        assert delta == {"removed": [], "changed": [], "added": ["fn own (A/own.rs)"]}, delta


def test_single_base_is_unchanged():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        repo, base, team = setup(tmp)
        sh(repo, "branch", "integration", base)
        sh(repo, "branch", "landing", base)
        tree = tmp / "tree"
        sh(repo, "worktree", "add", "-q", "-b", "wo/A/w", str(tree), "integration")
        commit(tree, "A/own", "own\n", "own")
        assert cl.own_base(team, tree) == base
        assert merged_base_for(team, tree) is None


def test_conflicting_bases_fall_back_to_previous_answer():
    with tempfile.TemporaryDirectory() as d:
        repo, tree, team, i, m = criss_cross(Path(d), conflict=True)
        old = sh(tree, "merge-base", "HEAD", "refs/heads/landing")
        assert old in (i, m), old
        assert cl.own_base(team, tree) == old
        assert merged_base_for(team, tree) is None


if __name__ == "__main__":
    import inspect
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn()
                print(f"  PASS {name}")
            except Exception as ex:
                failed += 1
                print(f"  FAIL {name}: {type(ex).__name__}: {ex}")
    print("all passed" if not failed else f"{failed} failed")
    raise SystemExit(1 if failed else 0)
