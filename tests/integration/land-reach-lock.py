#!/usr/bin/env -S python3 -u
"""Lockfile and documentation reach in a throwaway Git workspace."""
import importlib.machinery
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

HOME = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl", str(HOME / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader("cl", loader)
cl = importlib.util.module_from_spec(spec)
sys.modules["cl"] = cl
loader.exec_module(cl)

LOCK = '''version = 3

[[package]]
name = "a"
version = "1.0.0"
dependencies = ["reg-a"]

[[package]]
name = "b"
version = "1.0.0"
dependencies = ["a"]

[[package]]
name = "c"
version = "1.0.0"
dependencies = ["reg-c"]

[[package]]
name = "reg-a"
version = "1.0.0"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

[[package]]
name = "reg-c"
version = "1.0.0"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
'''
ALL = ["za", "zb", "zc"]


def git(tree, *args):
    return subprocess.run(["git", "-C", str(tree), *args], check=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()


def commit(tree, message):
    git(tree, "add", "-A")
    git(tree, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", message)
    return git(tree, "rev-parse", "HEAD")


def workspace(root, lock_at_base=True, nested_lock=False):
    tree = root / "tree"
    tree.mkdir()
    (tree / "Cargo.toml").write_text('[workspace]\nmembers = ["crates/*"]\n')
    for name in ("a", "b", "c"):
        folder = tree / "crates" / name
        folder.mkdir(parents=True)
        deps = '\n[dependencies]\na = { path = "../a" }\n' if name == "b" else ""
        (folder / "Cargo.toml").write_text(f'[package]\nname = "{name}"\nversion = "1.0.0"\n' + deps)
    (tree / "crates/a/README.md").write_text("a docs\n")
    (tree / "docs").mkdir()
    (tree / "docs/x.md").write_text("docs\n")
    (tree / "Makefile").write_text("all:\n")
    if lock_at_base:
        (tree / "Cargo.lock").write_text(LOCK)
    if nested_lock:
        (tree / "nested").mkdir()
        (tree / "nested/Cargo.lock").write_text(LOCK)
    git(tree, "init", "-q")
    base = commit(tree, "base")
    lanes = ''.join(f'[[lanes]]\nname = "z{n}"\npath = "crates/{n}"\n' for n in "abc")
    (root / "team.toml").write_text(f'repo = "{tree}"\nworktree_root = "{root / "root"}"\n' + lanes)
    return tree, base, cl.Team(str(root / "team.toml"), create=False)


def changed_version(lock, name):
    return lock.replace(f'name = "{name}"\nversion = "1.0.0"', f'name = "{name}"\nversion = "2.0.0"')


def check_case(root, case, files, expected, *, use_base=True, lock_at_base=True):
    tree, base, team = workspace(root, lock_at_base, nested_lock=case == "nested_no_manifest")
    if case == "a_dependency":
        lock = LOCK.replace('dependencies = ["reg-a"]', 'dependencies = ["reg-a", "reg-c"]', 1)
    elif case in ("c", "reg-a", "reg-c"):
        lock = changed_version(LOCK, case)
    elif case == "invalid":
        lock = '[[package]\nnot toml\n'
    elif case == "new":
        lock = LOCK
    elif case == "unknown":
        lock = LOCK + '\n[[package]]\nname = "missing"\nversion = "1.0.0"\n'
    elif case == "duplicate":
        lock = changed_version(LOCK, "c")
        folder = tree / "crates" / "duplicate"
        folder.mkdir()
        (folder / "Cargo.toml").write_text('[package]\nname = "c"\nversion = "1.0.0"\n')
    elif case == "root_package":
        lock = LOCK + '\n[[package]]\nname = "root"\nversion = "1.0.0"\n'
        (tree / "Cargo.toml").write_text('[package]\nname = "root"\nversion = "1.0.0"\n'
                                         '[workspace]\nmembers = ["crates/*"]\n')
    elif case == "nested_no_manifest":
        (tree / "nested/Cargo.lock").write_text(changed_version(LOCK, "c"))
        lock = LOCK
    else:
        lock = LOCK
    (tree / "Cargo.lock").write_text(lock)
    commit(tree, "scenario") if git(tree, "status", "--porcelain") else None
    actual = cl.reach(team, str(tree), files, base=base) if use_base else cl.reach(team, str(tree), files)
    assert actual == expected, f"expected {expected}, got {actual}"


CASES = [
    ("member_a_gains_dependency", "a_dependency", ["Cargo.lock"], ["za", "zb"], {}),
    ("member_c_changes", "c", ["Cargo.lock"], ["zc"], {}),
    ("registry_used_by_c_bumps", "reg-c", ["Cargo.lock"], ["zc"], {}),
    ("registry_used_by_a_bumps", "reg-a", ["Cargo.lock"], ["za", "zb"], {}),
    ("lock_without_base", "c", ["Cargo.lock"], ALL, {"use_base": False}),
    ("invalid_lock", "invalid", ["Cargo.lock"], ALL, {}),
    ("lock_absent_at_base", "new", ["Cargo.lock"], ALL, {"lock_at_base": False}),
    ("nested_lock_without_manifest", "nested_no_manifest", ["nested/Cargo.lock"], ALL, {}),
    ("unowned_doc", "none", ["docs/x.md"], [], {"use_base": False}),
    ("owned_doc", "none", ["crates/a/README.md"], ["za", "zb"], {"use_base": False}),
    ("unowned_doc_and_c_lock", "c", ["docs/x.md", "Cargo.lock"], ["zc"], {}),
    ("unowned_non_doc", "none", ["Makefile"], ALL, {"use_base": False}),
    ("unknown_package_folder", "unknown", ["Cargo.lock"], ALL, {}),
    ("duplicate_package_folder", "duplicate", ["Cargo.lock"], ALL, {}),
    ("workspace_root_package", "root_package", ["Cargo.lock"], ALL, {}),
]

failed = 0
for name, case, files, expected, options in CASES:
    root = Path(tempfile.mkdtemp(prefix=f"reach-lock-{name}-"))
    try:
        check_case(root, case, files, expected, **options)
    except Exception:
        failed += 1
        print(f"  FAIL {name} ({root} kept for a look)", flush=True)
        traceback.print_exc()
    else:
        shutil.rmtree(root)
        print(f"  PASS {name}")
print(f"{failed} failed" if failed else "all passed")
sys.exit(1 if failed else 0)
