#!/usr/bin/env -S python3 -u
"""Landing's reached roots and Stage 2/5 step selection, with fake collaborators."""
import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "share"))
loader = importlib.machinery.SourceFileLoader("cl_reach2", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)


def team(selector=None):
    values = {"rit_selector": selector}
    return SimpleNamespace(zones={"owner": ["src", "tests/unit/land-*.py"], "caller": ["caller"], "other": ["other"]},
                           m={"lanes": [{"name": "owner", "path": "src"}, {"name": "caller", "path": "caller"},
                                        {"name": "other", "path": "other"}]}, cfg={},
                           c=lambda key, default=None: values.get(key, default))


def test_glob_test_owner_excludes_other_scopes():
    zt = SimpleNamespace(scope_dirs=lambda tree, root, depth: ["tests/unit", root])
    with patch.object(cl, "zone_tool", return_value=zt), patch.object(Path, "exists", return_value=True):
        assert cl.reach(team(), "/tree", ["tests/unit/land-x.py"]) == ["owner"]


def test_test_owner_still_reaches_contract_consumer():
    tm = team()
    tm.cfg["contracts"] = {"tests/unit/land-x.py": ["caller"]}
    zt = SimpleNamespace(scope_dirs=lambda tree, root, depth: ["tests/unit", root])
    with patch.object(cl, "zone_tool", return_value=zt), patch.object(Path, "exists", return_value=True):
        assert cl.reach(tm, "/tree", ["tests/unit/land-x.py"]) == ["caller", "owner"]


def test_test_folders_narrows_both_groups_and_adds_rust():
    tm = team()
    tm.zones["owner"] = ["kit", "unrelated"]
    scopes = {"kit": ["kit!rust"], "kit/rust": ["kit/rust"], "unrelated": ["unrelated"]}
    zt = SimpleNamespace(scope_dirs=lambda tree, root, depth: scopes[root])
    with patch.object(cl, "test_folder", return_value=True), patch.object(cl, "zone_tool", return_value=zt), \
            patch.object(cl, "nested_crate_root", side_effect=lambda tree, root: "kit/rust" if root == "kit" else None, create=True):
        for group in ("unit", "integration"):
            assert cl.test_folders(tm, "/tree", "owner", group, ["kit/rust/src/lib.rs"]) == ["kit/rust"], group


def test_test_folders_dependency_document_reaches_no_dependent_root():
    """Kit/AGENTS.md is kit's, not app's, though app depends on kit; kit's code still is."""
    tm = team()
    tm.zones["owner"] = ["app"]
    zt = SimpleNamespace(scope_dirs=lambda tree, root, depth: ["app", "kit", "scripts"])
    packages = {"/tree/app/Package.swift", "/tree/kit/Package.swift"}
    with patch.object(cl, "test_folder", return_value=True), patch.object(cl, "zone_tool", return_value=zt), \
            patch.object(cl, "nested_crate_root", return_value=None), \
            patch.object(Path, "is_file", lambda self: str(self) in packages):
        assert cl.test_folders(tm, "/tree", "owner", "unit", ["kit/AGENTS.md"]) == []
        assert cl.test_folders(tm, "/tree", "owner", "integration", ["kit/Sources/Kit/a.swift"]) == ["app"]
        assert cl.test_folders(tm, "/tree", "owner", "unit", ["app/AGENTS.md", "kit/AGENTS.md"]) == ["app"]
        assert cl.test_folders(tm, "/tree", "owner", "unit", ["scripts/README.md"]) == ["app"]


def test_test_folders_empty_files_unchanged():
    tm = team()
    tm.zones["owner"] = ["kit", "unrelated"]
    with patch.object(cl, "test_folder", return_value=True):
        assert cl.test_folders(tm, "/tree", "owner", "unit", []) == ["kit", "unrelated"]


def integration_steps(selector, recheck):
    tm = team(selector)
    files = ["src/lib.rs"]
    zones = ["owner", "caller"]
    rec = {"tree": "/tree", "files": files}
    batches = []
    def stage(team, rec, steps, group, **kwargs):
        batches.append((group, steps))
        return True
    with patch.object(cl, "duplicate_rulings", return_value=[]), patch.object(cl, "reach", return_value=zones), \
            patch.object(cl, "compile_steps", return_value=[]), patch.object(cl, "repo_test_steps", return_value=[]), \
            patch.object(cl, "repo_integration_steps", return_value=[]), patch.object(cl, "stage2_steps", side_effect=stage), \
            patch.object(cl, "test_folders", side_effect=lambda team, tree, zone, group, files: [zone + "/tests"]), \
            patch.object(cl, "rit_roots", side_effect=lambda tree, roots, selector: roots, create=True):
        if recheck:
            return cl.recheck_steps(tm, Path("/tree"), zones, files)[1]
        cl.check_integration(tm, rec, False)
        return batches[-1][1]


def test_check_integration_defers_selector_steps_to_landing():
    assert integration_steps("rit_", False) == []


def test_recheck_selector_uses_rit_for_caller():
    assert [name for name, _ in integration_steps("rit_", True)] == ["tests owner (owner/tests)", "rits caller (caller/tests)"]


def test_selector_without_files_keeps_every_zit():
    tm = team("rit_")
    with patch.object(cl, "compile_steps", return_value=[]), \
            patch.object(cl, "repo_integration_steps", return_value=[]), \
            patch.object(cl, "zone_tests", side_effect=lambda team, tree, zone, cls, group, files: [
                (f"tests {zone} ({zone}/tests)", f"zit {zone}/tests")]), \
            patch.object(cl, "lane_rec", return_value={}), \
            patch.object(cl, "test_folders", side_effect=lambda team, tree, zone, group, files: [zone + "/tests"]), \
            patch.object(cl, "rit_roots", side_effect=lambda tree, roots, selector: roots):
        _, steps = cl.recheck_steps(tm, Path("/tree"), ["A", "B"], [])
    assert [name for name, _ in steps] == ["tests A (A/tests)", "tests B (B/tests)"]


def test_check_integration_defers_unselected_zits_to_landing():
    assert integration_steps(None, False) == []


def test_recheck_no_selector_keeps_zits():
    assert [name for name, _ in integration_steps(None, True)] == ["tests owner (owner/tests)", "tests caller (caller/tests)"]


def test_repo_integration_steps_narrows_scripts():
    scripts = [Path("/tree/tests/integration/test_a.py"), Path("/tree/tests/integration/test_b.py")]
    with patch.object(Path, "is_dir", return_value=True), patch.object(Path, "is_file", return_value=True), \
            patch.object(Path, "glob", side_effect=lambda pattern: scripts if pattern == "*.py" else []), \
            patch.object(cl, "reaching_tests", return_value=["tests/integration/test_a.py"], create=True):
        try:
            steps = cl.repo_integration_steps("/tree", "tests/integration", "land", "zone-tool",
                                              files=["src/a.py"], docs=(".md",))
        except TypeError:
            assert False, "repo_integration_steps does not accept changed files"
    assert len(steps) == 1
    assert "only=test_a.py" in steps[0][1]
    assert "tests/integration/test_a.py" in steps[0][1]
    assert "tests/integration/test_b.py" not in steps[0][1]


def test_restart_targets_new_modules():
    for module in ("test_file", "reached_roots", "nested_crate", "reaching_tests", "rit_command", "rit_roots",
                   "reached_zone_steps", "owning_zone"):
        assert cl.restart_targets([f"share/codeteam_{module}.py"])["runners"], module


failed = 0
for name, test in list(globals().items()):
    if name.startswith("test_") and callable(test):
        try:
            test()
            print(f"PASS {name}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
print(f"{failed} failed" if failed else "all passed")
sys.exit(bool(failed))
