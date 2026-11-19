#!/usr/bin/env -S python3 -u
"""The landed-Markdown check reports file names that name no tracked file, except on a line marked
<!-- external -->: another repository's files or a package's own contents, and except a name
already on a line the landing removed, which the landing did not add.
"""
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



def test_a_name_already_on_the_edited_line_is_not_reported():
    # an old changelog entry names a file that has moved since; the work order only rewords the commit id on that line
    removed = ["- census: VaultKit/rust/tests/palace_init_refusal.rs refuses (1a2b3c4)"]
    added = ["- census: VaultKit/rust/tests/palace_init_refusal.rs refuses (5d6e7f8)"]
    assert cl.missing_file_refs(added, TRACKED, NAMES, removed) == []


def test_a_name_new_on_an_edited_line_is_still_reported():
    assert cl.missing_file_refs(["See a.swift and gone.rs."], TRACKED, NAMES, ["See a.swift."]) == ["gone.rs"]



def test_a_swift_extension_name_keeps_its_plus_sign():
    """Type+Extension.swift is the house name for an extension file; the check split it at the plus
    sign and reported ManagerLane.swift, which no file is called."""
    tracked = TRACKED + ["apps/d/Sources/D/CommunityResidentMain+ManagerLane.swift"]
    names = {**NAMES, "CommunityResidentMain+ManagerLane.swift": tracked[-1:]}
    line = "The seam is in `CommunityResidentMain+ManagerLane.swift` and D/CommunityResidentMain+ManagerLane.swift:40."
    assert cl.missing_file_refs([line], tracked, names) == []
    assert cl.missing_file_refs(["See EstateAdmin+NewDatabase.swift."], tracked, names) == ["EstateAdmin+NewDatabase.swift"]

if __name__ == "__main__":
    for fn in (test_a_missing_file_is_reported_and_a_tracked_one_is_not, test_a_marked_line_is_skipped,
               test_the_mark_covers_its_own_line_only, test_a_name_already_on_the_edited_line_is_not_reported,
               test_a_name_new_on_an_edited_line_is_still_reported, test_a_swift_extension_name_keeps_its_plus_sign):
        fn()
    print("all passed")
