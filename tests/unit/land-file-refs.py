#!/usr/bin/env -S python3 -u
"""The landed-Markdown check reports file names that name no tracked file, except on a line marked
<!-- external -->: another repository's files or a package's own contents."""
import importlib.machinery
import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_refs", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)

TRACKED = ["A/Sources/a.swift", "docs/reference/A_SPEC.md"]
NAMES = {"a.swift": ["A/Sources/a.swift"], "A_SPEC.md": ["docs/reference/A_SPEC.md"]}


def test_a_missing_file_is_reported_and_a_tracked_one_is_not():
    assert cl.missing_file_refs(["See a.swift and A/Sources/gone.swift:12."], TRACKED, NAMES) == ["A/Sources/gone.swift"]


def test_a_marked_line_is_skipped():
    line = "other-lab at 1a2b3c: lab/loop_handover.py and vectors/vectors.json <!-- external -->"
    assert cl.missing_file_refs([line], TRACKED, NAMES) == []


def test_the_mark_covers_its_own_line_only():
    lines = ["finder_loop.json <!-- External -->", "selector_manifest.json"]
    assert cl.missing_file_refs(lines, TRACKED, NAMES) == ["selector_manifest.json"]


if __name__ == "__main__":
    for fn in (test_a_missing_file_is_reported_and_a_tracked_one_is_not, test_a_marked_line_is_skipped,
               test_the_mark_covers_its_own_line_only):
        fn()
    print("all passed")
