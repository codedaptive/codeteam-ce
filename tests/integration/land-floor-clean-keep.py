#!/usr/bin/env -S python3 -u
"""The disk-floor clean on the validation clone removes ignored build output but keeps the manifest's keep folders,
even when the keep folder is itself ignored (2026-11-11: an exclude pathspec let git clean -d remove an
ignored model weights folder whole). Runs the real command against a real git repo in a temp folder."""
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
loader = importlib.machinery.SourceFileLoader("cl_floor", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True,
                   capture_output=True)


def test_ignored_keep_folder_survives_and_build_output_goes():
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d) / "clone"
        (repo / "tools" / "ne").mkdir(parents=True)
        (repo / "tools" / "ne" / "fetch.sh").write_text("x\n")
        (repo / ".gitignore").write_text("tools/ne/models/\nbuild/\n.codegraph/\n")
        git(repo, "init", "-q")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "init")
        for f in ("tools/ne/models/config.json", "tools/ne/models/sub/w.bin", "build/o", ".codegraph/db"):
            (repo / f).parent.mkdir(parents=True, exist_ok=True)
            (repo / f).write_text("w\n")
        subprocess.run(cl.floor_clean_command(str(repo), ["tools/ne/models"]), shell=True, check=True)
        assert (repo / "tools/ne/models/config.json").exists()
        assert (repo / "tools/ne/models/sub/w.bin").exists()
        assert (repo / ".codegraph/db").exists()
        assert not (repo / "build").exists()
        assert (repo / "tools/ne/fetch.sh").exists()


if __name__ == "__main__":
    test_ignored_keep_folder_survives_and_build_output_goes()
    print("  PASS test_ignored_keep_folder_survives_and_build_output_goes")
