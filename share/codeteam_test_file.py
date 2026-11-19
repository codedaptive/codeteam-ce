"""Whether a changed path is a test file (D491, creator #4379 Q-stage2-reach2).

Landing's reach sends a changed test file to the zone that owns it and no further: a test file is read by its own
test target, not by the packages whose scope happens to cover its folder. TEST_MARKS is the substring form the
interface check (bin/codeteam-land) uses to leave test declarations out; is_test_file applies the same marks to the
path's folders and file name, adds `__tests__` folders, pytest's `test_*.py` and Rust's out-of-line unit-test module
(a file named exactly `tests.rs`, declared `#[cfg(test)] mod tests;`; D565), and takes a team's own globs.
"""
from collections.abc import Iterable
from fnmatch import fnmatchcase

TEST_MARKS = ("/tests/", "/Tests/", "_tests.", "_test.", "Tests.swift", "/test/")
TEST_FOLDERS = {"tests", "Tests", "__tests__", "test"}


def is_test_file(path: str, globs: Iterable[str] = ()) -> bool:
    """True when a folder on `path` (not its file name) is a test folder, the file name is a test file's
    (`_test.`, `_tests.`, `...Tests.swift`, `test_*.py`, exactly `tests.rs`), or `path` matches one of `globs`.
    Path only: a `tests.rs` its parent does not declare under `#[cfg(test)]` is still read as a test file (D565)."""
    *folders, name = path.split("/")
    return (any(folder in TEST_FOLDERS for folder in folders)
            or "_test." in name or "_tests." in name or name.endswith("Tests.swift")
            or fnmatchcase(name, "test_*.py") or name == "tests.rs"
            or any(fnmatchcase(path, glob) for glob in globs))
