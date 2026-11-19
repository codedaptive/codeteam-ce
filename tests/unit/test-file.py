#!/usr/bin/env -S python3 -u
"""Test-file recognition at landing's ownership boundary."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_test_file import TEST_MARKS, is_test_file


def test_named_folders():
    for path in ("crates/widgets/tests/resolve/x.rs", "tests/unit/land-x.py",
                 "packages/kits/K/Tests/KTests/FooTests.swift", "a/__tests__/foo.js", "a/test/foo.rb"):
        assert is_test_file(path), path


def test_filename_patterns():
    for path in ("a/b/foo_test.go", "a/foo_tests.py", "a/FooTests.swift", "a/test_thing.py"):
        assert is_test_file(path), path


def test_non_test_names():
    for path in ("src/contest.rs", "src/testing.rs", "crates/a/src/lib.rs", "src/tests", "src/test.txt"):
        assert not is_test_file(path), path


def test_rust_out_of_line_test_module():
    for path in ("rust/src/tests.rs", "crates/x/src/foo/tests.rs"):
        assert is_test_file(path), path


def test_rust_names_that_only_contain_tests():
    for path in ("rust/src/attests.rs", "rust/src/tests_util.rs", "rust/src/lib.rs"):
        assert not is_test_file(path), path


def test_configured_glob():
    assert is_test_file("spec/x.rb", ["spec/**"])
    assert not is_test_file("other/x.rb", ["spec/**"])


def test_legacy_marks():
    assert TEST_MARKS == ("/tests/", "/Tests/", "_tests.", "_test.", "Tests.swift", "/test/")


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
