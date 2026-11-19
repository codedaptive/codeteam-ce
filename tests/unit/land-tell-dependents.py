#!/usr/bin/env -S python3 -u
"""tell_dependents tells the zones that depend on the work order's zone: what the zone's own owned folders and files
reach, not the work order's recorded reach. A SPEC or INTERFACE under docs/ is in no zone's scope and reaches nothing,
so a work order that changed only its zone's INTERFACE recorded no reach and told nobody (the merge gate's
land-docs.py, 2026-11-14). reach, git and the open records are faked; the ledgers are in a temp folder."""
import importlib.machinery
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_tell_dependents", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)


def told(zones, recorded, reached, open_zones=()):
    """Run tell_dependents for zone A with zones' owned paths; the zones whose ledger got a line, and the paths reach
    was asked about (None when it was not called)."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        for z in zones:
            (root / "workcrews" / z).mkdir(parents=True)
        team = SimpleNamespace(zones=zones, root=root, repo=str(root), lab=False)
        rec = {"zone": "A", "wo": "iface", "reach": recorded, "tree": str(root / "gone")}
        asked = []

        def fake_reach(team_, tree, files, base=None):
            asked.append(list(files))
            return reached
        with patch.object(cl, "reach", side_effect=fake_reach), \
                patch.object(cl, "open_records", return_value=[(None, {"zone": z}) for z in open_zones]), \
                patch.object(cl, "out", return_value=""):
            cl.tell_dependents(team, rec, "abc1234567", ["docs/reference/A_INTERFACE.md"])
        lines = sorted(z for z in zones
                       if (root / "workcrews" / z / "ledger" / "reports" / "dependency-changes.md").exists())
        return lines, (asked[0] if asked else None)


def test_the_zones_that_depend_on_the_zone_are_told_though_the_document_reached_nothing():
    zones = {"A": ["packages/A"], "B": ["packages/B"], "C": ["packages/C"]}
    assert told(zones, recorded=[], reached=["A", "B"]) == (["B"], ["packages/A"])


def test_a_dependent_with_an_open_work_order_is_not_told_here():
    zones = {"A": ["packages/A"], "B": ["packages/B"]}
    assert told(zones, recorded=[], reached=["A", "B"], open_zones=["B"])[0] == []


def test_the_zones_globs_are_left_out_of_what_reach_is_asked():
    zones = {"A": ["packages/A", "tools/*.py"], "B": ["packages/B"]}
    assert told(zones, recorded=[], reached=["A", "B"])[1] == ["packages/A"]


def test_a_zone_that_owns_only_globs_uses_the_recorded_reach():
    zones = {"A": ["tools/*.py"], "B": ["packages/B"], "C": ["packages/C"]}
    assert told(zones, recorded=["A", "C"], reached=["B"]) == (["C"], None)


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS {name}")
            except (Exception, SystemExit) as exc:
                failed += 1
                print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"{failed} failed" if failed else "all passed")
    sys.exit(1 if failed else 0)
