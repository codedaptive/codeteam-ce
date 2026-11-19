#!/usr/bin/env -S python3 -u
"""Interface notices retain known callers and report incomplete answers."""
import importlib.machinery
import importlib.util
import json
import os
import shlex
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_interface_callers", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
loader.exec_module(cl)
ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_AUTHOR_DATE="2001-01-01T00:00:00Z",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t", GIT_COMMITTER_DATE="2001-01-01T00:00:00Z",
           CODETEAM_LAND_TOOL="1")


def sh(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, env=ENV, check=True, capture_output=True, text=True).stdout.strip()


def interface_result(truncated=False):
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        tmp = Path(directory)
        tree = tmp / "repo"
        tree.mkdir()
        sh(tree, "init", "-q", "-b", "main")
        (tree / "base").write_text("base\n")
        sh(tree, "add", "base")
        sh(tree, "commit", "-qm", "base")
        sh(tree, "branch", "integration")
        sh(tree, "branch", "landing")
        (tree / "A").mkdir()
        (tree / "A/own.rs").write_text("pub fn own() {}\n")
        sh(tree, "add", "A/own.rs")
        sh(tree, "commit", "-qm", "own")
        manifest = tmp / "team.toml"
        manifest.write_text(f'repo = "{tree}"\nworktree_root = "{tmp / "team"}"\n'
                            '[[lanes]]\nname = "A"\npath = "A"\n'
                            '[[lanes]]\nname = "B"\npath = "B"\n[land]\n')
        team = cl.Team(manifest)
        blast = {"changed": [{"path": "A/own.rs", "hunks": [{"lines": [{"n": 1, "sign": "+"}]}]}],
                 "seeds": [{"kind": "function", "name": "own", "path": "A/own.rs", "span": "L1-L1"}]}
        callers = {"callers": [{"path": "B/caller.rs"}], "total": 300 if truncated else 1,
                   "limit": 10000, "truncated": truncated,
                   "definitions": [{"callers": [{"path": "B/caller.rs"}], "total": 1,
                                    "limit": 10000, "truncated": False}]}
        log = tmp / "argv"
        cg = tmp / "fake-codegraph"
        cg.write_text("#!/bin/sh\nif [ \"$1\" = blast ]; then\n  printf '%s\\n' " + shlex.quote(json.dumps(blast)) +
                      "\nelse\n  printf '%s\\n' \"$@\" > " + shlex.quote(str(log)) +
                      "\n  printf '%s\\n' " + shlex.quote(json.dumps(callers)) + "\nfi\n")
        cg.chmod(0o755)
        previous = cl.CG
        cl.CG = str(cg)
        rec = {"tree": str(tree), "zone": "A"}
        try:
            found = cl.interface_changes(team, rec)
        finally:
            cl.CG = previous
        return found, rec, log.read_text().splitlines()


def test_complete_callers_report_zone_without_error():
    found, rec, _ = interface_result()
    assert found == {"own (A/own.rs:L1-L1)": ["B"]}
    assert rec.get("interface_callers") == {"own (A/own.rs:L1-L1)": {"B": ["B/caller.rs"]}}
    assert "interface_error" not in rec


def test_truncated_callers_report_known_zone_and_error():
    found, rec, _ = interface_result(truncated=True)
    assert found == {"own (A/own.rs:L1-L1)": ["B"]}
    assert rec.get("interface_error") == "codegraph callers own: incomplete answer, calling zones may be missing"
    assert rec.get("interface_callers") == {"own (A/own.rs:L1-L1)": None}


def test_callers_request_full_limit():
    _, _, argv = interface_result()
    assert argv[-2:] == ["-l", "10000"]


def test_disabled_check_clears_stale_callers():
    team = Mock()
    team.c.return_value = False
    rec = {"interface_callers": {"old": {"B": ["old.rs"]}}}
    with patch.object(cl.shutil, "which", return_value="cg"):
        assert cl.interface_changes(team, rec) == {}
    assert rec.get("interface_callers") == {}


def test_blast_error_clears_stale_callers():
    team = Mock()
    team.c.return_value = True
    rec = {"tree": "/fake", "zone": "A", "interface_callers": {"old": {"B": ["old.rs"]}}}
    with patch.object(cl.shutil, "which", return_value="cg"), \
         patch.object(cl, "own_base", return_value="base"), \
         patch.object(cl, "interface_blast", return_value=({}, "blast failed")):
        assert cl.interface_changes(team, rec) == {}
    assert rec.get("interface_callers") == {}
    assert rec["interface_error"] == "blast failed"


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
