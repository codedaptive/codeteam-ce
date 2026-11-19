#!/usr/bin/env -S python3 -u
"""Unit contract for new-side added line numbers in a two-dot diff."""
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "share"))
from codeteam_diff_plus_lines import diff_plus_lines


class FakeGit:
    def __init__(self, text="", status=0, error=None):
        self.text, self.status, self.error = text, status, error
        self.calls = []

    def __call__(self, *args, env=None):
        self.calls.append(args)
        if self.error:
            raise self.error
        return SimpleNamespace(returncode=self.status, stdout=self.text)


def test_added_lines_from_multiple_hunks_and_files():
    git = FakeGit("""diff --git a/A/one.rs b/A/one.rs
--- a/A/one.rs
+++ b/A/one.rs
@@ -2,0 +3,2 @@
+first
+second
@@ -8,2 +10,3 @@
-old
+replacement
 context
+last
diff --git a/B/two.rs b/B/two.rs
--- a/B/two.rs
+++ b/B/two.rs
@@ -0,0 +1,2 @@
+alpha
+beta
""")
    assert diff_plus_lines(git, "base", "head") == {"A/one.rs": {3, 4, 10, 12}, "B/two.rs": {1, 2}}


def test_single_line_hunk_without_count():
    git = FakeGit("--- a/a\n+++ b/a\n@@ -8 +8 @@\n-old\n+new\n")
    assert diff_plus_lines(git, "base") == {"a": {8}}


def test_deleted_file_is_excluded():
    git = FakeGit("diff --git a/gone b/gone\n--- a/gone\n+++ /dev/null\n@@ -1 +0,0 @@\n-old\n")
    assert diff_plus_lines(git, "base") == {}


def test_failed_diff_returns_none():
    assert diff_plus_lines(FakeGit(status=1), "base") is None


def test_oserror_returns_none():
    assert diff_plus_lines(FakeGit(error=OSError("git unavailable")), "base") is None


def test_diff_uses_separate_base_and_head_not_three_dot():
    git = FakeGit()
    assert diff_plus_lines(git, "my-base", "my-head") == {}
    assert len(git.calls) == 1
    args = git.calls[0]
    assert args[0] == "diff" and "-U0" in args, args
    assert args[-2:] == ("my-base", "my-head"), args
    assert not any("..." in arg for arg in args), args


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn()
                print(f"  PASS {name}")
            except Exception as ex:
                failed += 1
                print(f"  FAIL {name}: {type(ex).__name__}: {ex}")
    print("all passed" if not failed else f"{failed} failed")
    raise SystemExit(1 if failed else 0)
