#!/usr/bin/env -S python3 -u
"""A work order's record is never seen half-written:
save_record writes a temporary file of the writer's own, flushes it to disk and moves it into place. An integration
test: two real threads write the same record at once. The unit tests are in
tests/unit/land-record-atomic.py."""
import importlib.machinery
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
        loader.exec_module(module)
    return module


cl = load("cl_record_atomic", ROOT / "bin" / "codeteam-land")


def scratch():
    return Path(tempfile.mkdtemp(prefix="land-record-atomic-"))


def test_two_writers_never_share_a_temporary_file():
    d = scratch()
    try:
        names, real_replace = [], Path.replace
        with patch.object(Path, "replace", lambda self, to: (names.append(self.name), real_replace(self, to))[1]):
            writers = [threading.Thread(target=cl.save_record, args=(d / "r.json", {"n": n})) for n in range(2)]
            for w in writers:
                w.start()
            for w in writers:
                w.join()
        assert len(names) == 2 and names[0] != names[1], names
        assert json.loads((d / "r.json").read_text())["n"] in (0, 1)
    finally:
        shutil.rmtree(d)


if __name__ == "__main__":
    for fn in (test_two_writers_never_share_a_temporary_file,):
        fn()
    print("all passed")
