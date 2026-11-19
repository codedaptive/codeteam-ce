#!/usr/bin/env -S python3 -u
"""share/codeteam_detached_wo_branches.py: an open work order's branch counts as checked out while the landing tool
has its tree on a detached HEAD. Records are files in a temp folder; no git runs."""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("codeteam_detached_wo_branches",
                                              ROOT / "share" / "codeteam_detached_wo_branches.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def records(d, *names):
    """One open record per name in d, its tree d/wo/<name> and its branch wo/z/<name>."""
    for name in names:
        (d / f"{name}.json").write_text(json.dumps({"wo": name, "tree": str(d / "wo" / name), "branch": f"wo/z/{name}"}))


def detached(d, name):
    return [f"worktree {d / 'wo' / name}", "HEAD 0123abcd", "detached"]


def on_branch(d, name):
    return [f"worktree {d / 'wo' / name}", "HEAD 0123abcd", f"branch refs/heads/wo/z/{name}"]


def test_an_open_record_whose_tree_is_detached_gives_its_branch():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        records(d, "w1", "w2")
        assert module.detached_wo_branches(d, ["worktree /repo", "branch refs/heads/main", *detached(d, "w1"),
                                               *on_branch(d, "w2")]) == {"wo/z/w1"}


def test_a_landed_or_retired_work_order_gives_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        records(d, "w1", "w2")
        (d / "w1.landed.json").write_text("{}")
        (d / "w2.retired.json").write_text("{}")
        assert module.detached_wo_branches(d, [*detached(d, "w1"), *detached(d, "w2")]) == set()


def test_a_landed_record_is_not_read_as_an_open_one():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "w1.landed.json").write_text(json.dumps({"tree": str(d / "wo" / "w1"), "branch": "wo/z/w1"}))
        assert module.detached_wo_branches(d, detached(d, "w1")) == set()


def test_an_unreadable_record_is_skipped():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        records(d, "w1")
        (d / "w2.json").write_text("not json")
        assert module.detached_wo_branches(d, [*detached(d, "w1"), *detached(d, "w2")]) == {"wo/z/w1"}


def test_a_detached_tree_no_record_names_gives_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        records(d, "w1")
        assert module.detached_wo_branches(d, ["worktree /elsewhere/itest", "HEAD 0123abcd", "detached"]) == set()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("all passed")
