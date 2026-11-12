#!/usr/bin/env -S python3 -u
"""Stage 3: a work order whose reviewer findings were all dropped lands with no new commit; one with a finding
still open is refused until something is committed. Git and findings are
faked; nothing touches a repo."""
import importlib.machinery
import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_dropped", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", stderr="", returncode=0)):
    loader.exec_module(cl)

REC = {"wo": "w1", "tip": "t" * 40}
PREVIOUS = {"reviewers": {"Kong": "findings"}, "seen": {"Kong": ["t" * 40]}}


def finding(state, by="Kong", wo="w1", fid="f#1"):
    return {"id": fid, "state": state, "by": by, "also": [], "wos": [wo]}


def ranges(findings, new=()):
    with patch.object(cl, "review_range", return_value=list(new)), \
            patch.object(cl, "all_findings", return_value=list(findings)):
        return cl.reviewer_ranges(SimpleNamespace(), REC, PREVIOUS, ["Kong"])


def refused(findings):
    try:
        ranges(findings)
    except SystemExit:
        return True
    return False


def test_all_findings_dropped_lands_with_no_new_commit():
    assert ranges([finding("dropped"), finding("dropped", fid="f#2")]) == {}


def test_a_finding_still_open_is_refused_until_a_commit():
    assert refused([finding("dropped"), finding("open", fid="f#2")])


def test_any_open_finding_on_the_work_order_still_holds_it():
    assert refused([finding("dropped"), finding("open", by="Perkins", fid="p#1")])


def test_another_work_orders_open_finding_does_not_hold_it():
    assert ranges([finding("dropped"), finding("open", wo="w2", fid="f#9")]) == {}


def test_new_commits_go_to_review_as_before():
    assert ranges([finding("open")], new=["n" * 40]) == {"Kong": ["n" * 40]}


if __name__ == "__main__":
    import inspect
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn()
                print(f"  PASS {name}")
            except Exception as ex:          # report every case, then fail once
                failed += 1
                print(f"  FAIL {name}: {type(ex).__name__}: {ex}")
    print("all passed" if not failed else f"{failed} failed")
    raise SystemExit(1 if failed else 0)
