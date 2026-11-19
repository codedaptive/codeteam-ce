import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_diff_ranges import diff_ranges


def test_added_lines_and_default_length():
    diff = '--- a/a.py\n+++ b/a.py\n@@ -1 +2,3 @@\n+x\n+y\n+z\n@@ -9 +12 @@\n+x\n'
    assert diff_ranges(diff) == {"a.py": [(2, 4), (12, 12)]}


def test_pure_deletion_records_anchor():
    assert diff_ranges('--- a/a.py\n+++ b/a.py\n@@ -5,2 +4,0 @@\n-x\n-y\n') == {"a.py": [(4, 4)]}


def test_separate_files_have_separate_ranges():
    diff = '--- a/a.py\n+++ b/a.py\n@@ -1 +2 @@\n+x\n--- a/b.py\n+++ b/b.py\n@@ -3 +4,2 @@\n+y\n+z\n'
    assert diff_ranges(diff) == {"a.py": [(2, 2)], "b.py": [(4, 5)]}


def test_deleted_file_has_empty_ranges():
    assert diff_ranges('--- a/removed.py\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-x\n-y\n') == {"removed.py": []}
