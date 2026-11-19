#!/usr/bin/env -S python3 -u
"""Changed Cargo.lock packages and their workspace dependants."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "share"))
from codeteam_lock_reach import lock_changed_folders  # noqa: E402


def test_member_gains_dependency():
    old = '''
[[package]]
name = "tool-status"
version = "0.1.0"
[[package]]
name = "extract-base"
version = "0.1.0"
'''
    new = '''
[[package]]
name = "tool-status"
version = "0.1.0"
dependencies = ["extract-base"]
[[package]]
name = "extract-base"
version = "0.1.0"
'''
    assert lock_changed_folders(old, new, {"tool-status": "crates/tool-status"}) == ["crates/tool-status"]


def test_registry_bump_reaches_direct_and_transitive_members():
    old = '''
[[package]]
name = "a"
version = "0.1.0"
dependencies = ["serde"]
[[package]]
name = "b"
version = "0.1.0"
dependencies = ["a"]
[[package]]
name = "c"
version = "0.1.0"
[[package]]
name = "serde"
version = "1.0.1"
source = "registry+https://example.invalid/index"
'''
    new = old.replace('version = "1.0.1"', 'version = "1.0.2"')
    assert lock_changed_folders(old, new, {"a": "crates/a", "b": "crates/b", "c": "crates/c"}) == [
        "crates/a", "crates/b"]


def test_registry_bump_reaches_member_through_registry_package():
    old = '''
[[package]]
name = "c"
version = "0.1.0"
dependencies = ["middle"]
[[package]]
name = "middle"
version = "1.0.0"
source = "registry+https://example.invalid/index"
dependencies = ["leaf"]
[[package]]
name = "leaf"
version = "1.0.1"
source = "registry+https://example.invalid/index"
'''
    new = old.replace('version = "1.0.1"', 'version = "1.0.2"')
    assert lock_changed_folders(old, new, {"c": "crates/c"}) == ["crates/c"]


def test_identical_lock_returns_empty_list():
    text = '[[package]]\nname = "a"\nversion = "1.0.0"\n'
    assert lock_changed_folders(text, text, {}) == []


def test_unparseable_old_lock_is_unknown():
    assert lock_changed_folders('[[package]', '', {}) is None


def test_unparseable_new_lock_is_unknown():
    assert lock_changed_folders('', '[[package]', {}) is None


def test_changed_member_missing_folder_is_unknown():
    assert lock_changed_folders('', '[[package]]\nname = "a"\nversion = "1.0.0"\n', {}) is None


def test_changed_member_with_none_folder_is_unknown():
    assert lock_changed_folders('', '[[package]]\nname = "a"\nversion = "1.0.0"\n', {"a": None}) is None


def test_registry_dependency_version_selects_only_matching_member():
    old = '''
[[package]]
name = "a"
version = "0.1.0"
dependencies = ["foo 1.0.0"]
[[package]]
name = "c"
version = "0.1.0"
dependencies = ["foo 2.0.0"]
[[package]]
name = "foo"
version = "1.0.0"
source = "registry+https://example.invalid/index"
[[package]]
name = "foo"
version = "2.0.0"
source = "registry+https://example.invalid/index"
'''
    new = old.replace('foo 2.0.0', 'foo 2.0.1').replace('version = "2.0.0"', 'version = "2.0.1"')
    assert lock_changed_folders(old, new, {"a": "crates/a", "c": "crates/c"}) == ["crates/c"]


def test_removed_member_uses_known_folder():
    old = '[[package]]\nname = "gone"\nversion = "0.1.0"\n'
    assert lock_changed_folders(old, '', {"gone": "crates/gone"}) == ["crates/gone"]


def test_changed_root_member_is_unknown():
    assert lock_changed_folders('', '[[package]]\nname = "root"\nversion = "0.1.0"\n', {"root": "."}) is None


def test_changed_member_with_empty_folder_is_unknown():
    assert lock_changed_folders('', '[[package]]\nname = "root"\nversion = "0.1.0"\n', {"root": ""}) is None


def test_same_key_changed_field_is_a_change():
    old = '[[package]]\nname = "a"\nversion = "1.0.0"\nchecksum = "old"\n'
    new = '[[package]]\nname = "a"\nversion = "1.0.0"\nchecksum = "new"\n'
    assert lock_changed_folders(old, new, {"a": "crates/a"}) == ["crates/a"]


def test_source_qualified_dependency_reaches_member():
    old = '''
[[package]]
name = "a"
version = "0.1.0"
dependencies = ["foo 1.0.0 (git+https://example.invalid/foo)"]
[[package]]
name = "foo"
version = "1.0.0"
source = "git+https://example.invalid/foo"
checksum = "old"
'''
    new = old.replace('checksum = "old"', 'checksum = "new"')
    assert lock_changed_folders(old, new, {"a": "crates/a"}) == ["crates/a"]


def test_folders_are_sorted_and_unique():
    old = '''
[[package]]
name = "z"
version = "1.0.0"
[[package]]
name = "a"
version = "1.0.0"
[[package]]
name = "b"
version = "1.0.0"
'''
    new = old.replace('version = "1.0.0"', 'version = "1.0.1"')
    assert lock_changed_folders(old, new, {"z": "crates/z", "a": "crates/a", "b": "crates/a"}) == [
        "crates/a", "crates/z"]


def test_external_change_needing_unknown_member_folder_is_unknown():
    old = '''
[[package]]
name = "a"
version = "1.0.0"
dependencies = ["foo"]
[[package]]
name = "foo"
version = "1.0.0"
source = "registry+https://example.invalid/index"
checksum = "old"
'''
    new = old.replace('checksum = "old"', 'checksum = "new"')
    assert lock_changed_folders(old, new, {}) is None


def test_version_less_entry_is_unknown():
    assert lock_changed_folders('', '[[package]]\nname = "a"\n', {"a": "crates/a"}) is None


def test_name_less_entry_is_unknown():
    assert lock_changed_folders('', '[[package]]\nversion = "1.0.0"\n', {"a": "crates/a"}) is None


def test_package_not_a_list_of_tables_is_unknown():
    assert lock_changed_folders('', 'package = ["a"]\n', {"a": "crates/a"}) is None


def test_non_string_dependency_is_unknown():
    new = '[[package]]\nname = "a"\nversion = "1.0.0"\ndependencies = [1]\n'
    assert lock_changed_folders('', new, {"a": "crates/a"}) is None


def test_same_name_and_version_from_two_sources_stay_apart():
    old = '''
[[package]]
name = "a"
version = "0.1.0"
dependencies = ["foo 1.0.0 (registry+https://example.invalid/index)"]
[[package]]
name = "c"
version = "0.1.0"
dependencies = ["foo 1.0.0 (git+https://example.invalid/foo)"]
[[package]]
name = "foo"
version = "1.0.0"
source = "registry+https://example.invalid/index"
checksum = "registry"
[[package]]
name = "foo"
version = "1.0.0"
source = "git+https://example.invalid/foo"
checksum = "old"
'''
    new = old.replace('checksum = "old"', 'checksum = "new"')
    assert lock_changed_folders(old, new, {"a": "crates/a", "c": "crates/c"}) == ["crates/c"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except AssertionError:
                print(f"FAIL {name}")
                raise
            print(f"PASS {name}")
    print("all passed")
