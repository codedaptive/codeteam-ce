#!/usr/bin/env -S python3 -u
"""checked_members refuses a landing set with carried_check's text before it checks any member.
A zone unit test of codeteam-land: the check, the records and the member checks are fakes; nothing touches a
repo."""
import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "share"))
loader = importlib.machinery.SourceFileLoader("cl_carried", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", stderr="", returncode=0)):
    loader.exec_module(cl)


class Refused(Exception):
    pass


def refuse(msg, code=1):
    raise Refused(msg)


def checked(answer):
    """checked_members over one record with carried_check answering `answer`: (refusal text or None, the team and
    the faked entry_path, what carried_check was given, whether a member was checked)."""
    rec = {"wo": "comment", "zone": "a", "tree": "/t/comment"}
    team = SimpleNamespace(wo=lambda wo: rec, save_wo=Mock(), m={})
    check = Mock(return_value=answer)
    with patch.object(cl, "entry_path", return_value=None) as queue, patch.object(cl, "put_back_set_merge"), \
            patch.object(cl, "carried_check", check), patch.object(cl, "die", refuse), \
            patch.object(cl, "check_work_order", return_value=[]) as member, \
            patch.object(cl, "no_build_kind", return_value="docs-only"):
        try:
            cl.checked_members(team, ["comment"])
            text = None
        except Refused as stop:
            text = str(stop)
    return text, (team, queue), check.call_args.args, member.called


def test_a_set_that_carries_commits_is_refused_before_any_member_is_checked():
    text, _, _, member_checked = checked("comment carries unlanded commits of open work order host (c2)")
    assert text == "comment carries unlanded commits of open work order host (c2)"
    assert not member_checked


def test_the_check_gets_the_team_the_sets_records_and_the_land_tools_own_readers():
    _, (team, queue), (given_team, records, open_records, entry_path), _ = checked(None)
    assert given_team is team
    assert [rec["wo"] for rec in records] == ["comment"]
    assert open_records is cl.open_records and entry_path is queue


def test_a_set_that_carries_nothing_goes_on_to_its_member_checks():
    text, _, _, member_checked = checked(None)
    assert text is None and member_checked


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
