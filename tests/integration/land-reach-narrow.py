#!/usr/bin/env -S python3 -u
"""Landing reach and root selection in a throwaway workspace."""
import importlib.machinery
import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

HOME = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HOME / "share"))
loader = importlib.machinery.SourceFileLoader("cl_narrow", str(HOME / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
loader.exec_module(cl)
W = Path(tempfile.mkdtemp(prefix="land-reach-narrow-"))
T = W / "tree"


def put(path, text):
    file = T / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text)


put("Cargo.toml", '[workspace]\nmembers = ["crates/*"]\n')
put("crates/a/Cargo.toml", '[package]\nname = "a"\nversion = "0.1.0"\n')
put("crates/b/Cargo.toml", '[package]\nname = "b"\nversion = "0.1.0"\n[dependencies]\na = { path = "../a" }\n')
put("crates/c/Cargo.toml", '[package]\nname = "c"\nversion = "0.1.0"\n[dependencies]\nb = { path = "../b" }\n')
put("crates/t/Cargo.toml", '[package]\nname = "t"\nversion = "0.1.0"\n')
put("crates/t/tests/za/Cargo.toml", '[dependencies]\na = { path = "../../../a" }\n')
put("crates/t/tests/zb/Cargo.toml", '[dependencies]\nb = { path = "../../../b" }\na = { path = "../../../a" }\nza = { path = "../za" }\n')
put("crates/t/tests/skip/Cargo.toml", '[dependencies]\nc = { path = "../../../c" }\n')
put("crates/t/tests/skip/check.rs", "fn rit_skip() {}\n")
put("crates/t/tests/za/check.rs", "fn rit_a() {}\n")
put("crates/t/tests/zb/check.rs", "fn rit_b() {}\n")
put("crates/a/src/lib.rs", "pub fn a() {}\n")
put("kit/Package.swift", "let p = Package()\n")
put("kit/rust/Cargo.toml", '[package]\nname = "kit"\nversion = "0.1.0"\n')
put("kit/rust/src/lib.rs", "pub fn kit() {}\n")
(W / "team.toml").write_text(f'repo = "{T}"\nworktree_root = "{W / "root"}"\n'
    '[[lanes]]\nname = "a"\npath = "crates/a"\nowns = ["crates/t/tests/za"]\n'
    '[[lanes]]\nname = "b"\npath = "crates/b"\nowns = ["crates/t/tests/zb", "crates/t/tests/skip"]\n'
    '[[lanes]]\nname = "c"\npath = "crates/c"\n'
    '[[lanes]]\nname = "kit"\npath = "kit"\n')
subprocess.run(["git", "-C", str(T), "init", "-q"], check=True)
subprocess.run(["git", "-C", str(T), "add", "."], check=True)
tm = cl.Team(str(W / "team.toml"), create=False)


def test_test_file_reaches_only_owner():
    assert cl.reach(tm, str(T), ["crates/t/tests/za/check.rs"]) == ["a"]


def test_source_change_narrows_roots_in_both_groups():
    files = ["crates/a/src/lib.rs"]
    assert cl.reach(tm, str(T), files) == ["a", "b"]
    for group in ("unit", "integration"):
        assert cl.test_folders(tm, T, "a", group, files) == ["crates/a", "crates/t/tests/za"]
        assert cl.test_folders(tm, T, "b", group, files) == ["crates/b", "crates/t/tests/zb"]


def test_two_port_rust_selects_nested_root():
    files = ["kit/rust/src/lib.rs"]
    assert cl.test_folders(tm, T, "kit", "integration", files) == ["kit/rust"]
    assert [name for name, _ in cl.zone_tests(tm, T, "kit", "land", group="integration", files=files)] == [
        "tests kit (kit/rust)"]


def test_reached_zone_with_no_matching_root_has_no_steps():
    assert cl.zone_tests(tm, T, "c", "land", group="integration", files=["crates/a/src/lib.rs"]) == []


def test_stage2_and_recheck_step_names_match():
    files = ["crates/a/src/lib.rs"]
    recorded = []
    def capture(team, rec, steps, group, **kwargs):
        if group == "integration" and kwargs.get("kind") != "compile":
            recorded.extend(steps)
        return True
    with patch.object(cl, "duplicate_rulings", return_value=[]), patch.object(cl, "compile_steps", return_value=[]), \
            patch.object(cl, "repo_test_steps", return_value=[]), patch.object(cl, "repo_integration_steps", return_value=[]), \
            patch.object(cl, "stage2_steps", side_effect=capture):
        zones = cl.check_integration(tm, {"tree": str(T), "files": files}, False)
        _, recheck = cl.recheck_steps(tm, T, zones, files)
    expected = ["tests a (crates/a)", "tests a (crates/t/tests/za)", "tests b (crates/b)", "tests b (crates/t/tests/zb)"]
    assert recorded == []
    assert [name for name, _ in recheck] == expected


def test_selector_stage2_and_recheck_use_caller_rits():
    files = ["crates/a/src/lib.rs"]
    recorded = []
    def capture(team, rec, steps, group, **kwargs):
        if group == "integration" and kwargs.get("kind") != "compile":
            recorded.extend(steps)
        return True
    with patch.dict(tm.cfg, {"rit_selector": "rit_"}), patch.object(cl, "duplicate_rulings", return_value=[]), \
            patch.object(cl, "compile_steps", return_value=[]), patch.object(cl, "repo_test_steps", return_value=[]), \
            patch.object(cl, "repo_integration_steps", return_value=[]), patch.object(cl, "stage2_steps", side_effect=capture):
        zones = cl.check_integration(tm, {"tree": str(T), "files": files}, False)
        _, recheck = cl.recheck_steps(tm, T, zones, files)
    expected = ["tests a (crates/a)", "tests a (crates/t/tests/za)", "rits b (crates/t/tests/zb)"]
    assert recorded == []
    assert [name for name, _ in recheck] == expected


failed = 0
for name, test in list(globals().items()):
    if name.startswith("test_") and callable(test):
        try:
            test()
            print(f"PASS {name}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
if failed:
    print(f"{failed} failed ({W} kept)")
else:
    shutil.rmtree(W)
    print("all passed")
sys.exit(bool(failed))
