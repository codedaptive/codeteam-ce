#!/usr/bin/env -S python3 -u
"""Stage 2 puts back committed files its build changed, and a merge that fails without a conflict says why
(2026-11-12: a lane's unit build rewrote a stale Cargo.lock in the work order tree, and land's
`git merge integration` then failed with an empty 'conflicts in:' list). A lock the work order itself made stale, by
changing the manifest that feeds it, fails Stage 2 (2026-11-13). This file holds the unit
test (rule 11) of lock_inputs, which keeps only what a lock records; the tests that run Stage 2 and the merge in
real git repositories are in tests/integration/land-build-restore.py."""
import importlib.machinery
import importlib.util
import os
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ["CODETEAM_QUEUE_DIR"] = str(Path(tempfile.mkdtemp(prefix="land-queue-")) / "queue")

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_build_restore", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)


def test_lock_inputs_keep_only_what_the_lock_records():
    toml = "[package]\nname = \"a\"\nversion = \"1\"\ndescription = \"d\"\n[dependencies]\nx = \"1\"\n"
    assert cl.lock_inputs("Cargo.toml", toml) == cl.lock_inputs("Cargo.toml", toml.replace("\"d\"", "\"e\""))
    assert cl.lock_inputs("Cargo.toml", toml) != cl.lock_inputs("Cargo.toml", toml.replace("x = \"1\"", "x = \"2\""))
    assert cl.lock_inputs("Cargo.toml", None) is None
    assert cl.lock_inputs("Cargo.toml", "not = [toml") == "not = [toml"
    pkg = '{"name": "a", "description": "d", "dependencies": {"x": "1"}}'
    assert cl.lock_inputs("package.json", pkg) == cl.lock_inputs("package.json", pkg.replace('"d"', '"e"'))
    assert cl.lock_inputs("package.json", pkg) != cl.lock_inputs("package.json", pkg.replace('"1"', '"2"'))
    py = "[project]\nname = \"a\"\ndescription = \"d\"\ndependencies = [\"x\"]\n"
    assert cl.lock_inputs("pyproject.toml", py) == cl.lock_inputs("pyproject.toml", py.replace("\"d\"", "\"e\""))
    assert cl.lock_inputs("pyproject.toml", py) != cl.lock_inputs("pyproject.toml", py.replace("[\"x\"]", "[\"y\"]"))
    assert cl.lock_inputs("Package.swift", "// a\n") == "// a\n"     # Swift code counts whole


if __name__ == "__main__":
    test_lock_inputs_keep_only_what_the_lock_records()
    print("all passed")
