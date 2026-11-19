#!/usr/bin/env -S python3 -u
"""Stage 2 passes reach the base its files were measured from, with fake collaborators."""
import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_reach_base", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)

TEAM = SimpleNamespace(c=lambda key, default=None: default)


def test_check_integration_passes_base_to_reach():
    reach = Mock(return_value=["A"])
    rec = {"tree": "/T", "files": ["own"]}
    with patch.object(cl, "duplicate_rulings", return_value=[]), patch.object(cl, "reach", reach), \
            patch.object(cl, "stage2_steps", return_value=True), patch.object(cl, "compile_steps", return_value=[]), \
            patch.object(cl, "repo_test_steps", return_value=[]), patch.object(cl, "zone_tests", return_value=[]), \
            patch.object(cl, "repo_integration_steps", return_value=[]):
        cl.check_integration(TEAM, rec, False, files=["Cargo.lock"], base="B0")
    assert reach.call_args_list == [call(TEAM, "/T", ["Cargo.lock"], base="B0")], reach.call_args_list


def test_lone_member_measures_and_reaches_from_its_own_base():
    rec = {"tree": "/T", "branch": "wo/A/w", "zone": "A"}
    changed = Mock(return_value=["Cargo.lock"])
    check = Mock(return_value=["A"])
    reach = Mock(return_value=["A", "B"])
    git = Mock()
    with patch.object(cl, "own_base", return_value="OWNBASE"), patch.object(cl, "changed_files", changed), \
            patch.object(cl, "check_integration", check), patch.object(cl, "reach", reach), \
            patch.object(cl, "merge_set_tips") as merge, patch.object(cl, "git", git):
        assert cl.check_combined_members(TEAM, [(rec, None)], "INTEG") == (["A"], ["A", "B"])
    assert changed.call_args_list == [call("/T", "OWNBASE")], changed.call_args_list
    assert check.call_args_list == [call(TEAM, rec, False, files=["Cargo.lock"], base="OWNBASE")], check.call_args_list
    assert reach.call_args_list == [call(TEAM, "/T", ["Cargo.lock"], base="OWNBASE")], reach.call_args_list
    assert not merge.called and not git.called


failed = 0
for test in [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]:
    try:
        test()
        print(f"  PASS {test.__name__}")
    except (Exception, SystemExit) as exc:
        failed += 1
        print(f"  FAIL {test.__name__}: {type(exc).__name__}: {exc}")
print(f"{failed} failed" if failed else "all passed")
sys.exit(1 if failed else 0)
