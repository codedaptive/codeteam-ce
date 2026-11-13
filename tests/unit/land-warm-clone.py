#!/usr/bin/env -S python3 -u
"""wo-cut's warm clone copies only build folders lanes build into, never land/itest's own target/
(2026-11-12: each new tree got a 30 GB target/ no lane used)."""
import importlib.machinery
import importlib.util
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_warm", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)


def test_target_is_not_cloned_and_cargo_target_is():
    with patch.object(cl.subprocess, "run") as run, tempfile.TemporaryDirectory() as d:
        src, dest = Path(d) / "itest", Path(d) / "wo"
        for name in ("target", "cargo-target", ".build"):
            (src / name).mkdir(parents=True)
        dest.mkdir()
        cl.warm_clone(src, dest)
        copied = [Path(c.args[0][-1]).name for c in run.call_args_list]
        assert copied == ["cargo-target", ".build"], copied


def test_an_idle_tree_with_only_target_still_counts_as_build_output():
    assert "target" in cl.BUILD_OUTPUT_DIRS and "target" not in cl.WARM_DIRS


if __name__ == "__main__":
    test_target_is_not_cloned_and_cargo_target_is()
    test_an_idle_tree_with_only_target_still_counts_as_build_output()
    print("all passed")
