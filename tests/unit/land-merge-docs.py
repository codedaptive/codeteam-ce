#!/usr/bin/env -S python3 -u
"""merge_checked_base reruns a zone's unit tests after a base merge only when the merge brought in a file of that zone
that is not a document: a merge whose zone files are all documents (a promote's docs stamp
rewriting AGENTS.md inside a package) runs nothing, as a docs-only landing runs nothing. git and test_units are
faked; no repo, no process."""
import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_merge_docs", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)


def team(suffixes=None):
    cfg = {} if suffixes is None else {"docs_only_suffixes": suffixes}
    return SimpleNamespace(zones={"GLK": ["packages/kits/WidgetStoreKit"], "Other": ["packages/kits/Other"]},
                           integration="integration", c=lambda key, default: cfg.get(key, default))


def merge(merged_files, t=None, only_docs=None, test=True):
    """Run merge_checked_base with the merge bringing in merged_files; the paths test_units was called for."""
    rec = {"wo": "w1", "zone": "GLK", "tree": "/tree", "files": ["packages/kits/WidgetStoreKit/Sources/a.swift"]}
    heads = iter(["before", "after"])

    def out(tree, *args):
        if args[:1] == ("rev-parse",):
            return next(heads)
        if args[:2] == ("diff", "--name-only"):
            return "\n".join(merged_files)
        raise AssertionError(f"unexpected git call {args}")
    with patch.object(cl, "out", side_effect=out), \
            patch.object(cl, "git", return_value=SimpleNamespace(returncode=0)), \
            patch.object(cl, "work_order_files", return_value=rec["files"]), \
            patch.object(cl, "test_units") as units:
        cl.merge_checked_base(t or team(), rec, "integration", only_docs, test)
    return units.call_count


def test_a_merge_that_brings_only_documents_into_the_zone_runs_no_units():
    assert merge(["packages/kits/WidgetStoreKit/AGENTS.md", "packages/kits/WidgetStoreKit/docs/guide.md"]) == 0


def test_a_merge_that_brings_a_code_file_into_the_zone_runs_the_units():
    assert merge(["packages/kits/WidgetStoreKit/AGENTS.md", "packages/kits/WidgetStoreKit/Sources/b.swift"]) == 1


def test_a_merge_that_touches_only_another_zone_runs_no_units():
    assert merge(["packages/kits/Other/Sources/c.swift"]) == 0


def test_the_team_docs_suffixes_decide_what_a_document_is():
    assert merge(["packages/kits/WidgetStoreKit/notes.txt"], team([".md", ".txt"])) == 0
    assert merge(["packages/kits/WidgetStoreKit/notes.txt"]) == 1


def test_a_docs_only_work_order_and_a_no_test_call_still_run_nothing():
    assert merge(["packages/kits/WidgetStoreKit/Sources/b.swift"], only_docs="docs-only") == 0
    assert merge(["packages/kits/WidgetStoreKit/Sources/b.swift"], test=False) == 0


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
