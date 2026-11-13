#!/usr/bin/env -S python3 -u
"""wo-hold marks an open work order as held on purpose, with its ruling, and lifts the mark (2026-11-12:
a work order kept on its branch by a ruling was reported as stalled every patrol round)."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_hold", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)


class FakeTeam:
    def __init__(self, d):
        self.dir = Path(d)
        (self.dir / "wo").mkdir()

    wo_file = cl.Team.wo_file
    wo = cl.Team.wo
    save_wo = cl.Team.save_wo


def args(wo=None, because=None, release=False):
    return SimpleNamespace(wo=wo, because=because, release=release)


def run(team, a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cl.cmd_wo_hold(team, a)
    return buf.getvalue()


def test_hold_list_release():
    with tempfile.TemporaryDirectory() as d:
        team = FakeTeam(d)
        team.save_wo({"wo": "v2-SubstrateTypes", "zone": "SubstrateTypes", "tree": "/x", "base": "b"})
        team.save_wo({"wo": "other", "zone": "Z", "tree": "/y", "base": "b"})
        run(team, args("v2-SubstrateTypes", because="ruling 12 item 2, ruling 13 item 4"))
        held = json.loads(team.wo_file("v2-SubstrateTypes").read_text())["held"]
        assert held["because"] == "ruling 12 item 2, ruling 13 item 4" and held["at"], held
        listed = run(team, args())
        assert "v2-SubstrateTypes" in listed and "ruling 12 item 2" in listed and "other" not in listed, listed
        run(team, args("v2-SubstrateTypes", release=True))
        assert "held" not in json.loads(team.wo_file("v2-SubstrateTypes").read_text())
        assert run(team, args()) == ""


def test_hold_needs_a_reason():
    with tempfile.TemporaryDirectory() as d:
        team = FakeTeam(d)
        team.save_wo({"wo": "w", "zone": "Z", "tree": "/x", "base": "b"})
        for because in (None, "  "):
            try:
                with contextlib.redirect_stderr(io.StringIO()):
                    cl.cmd_wo_hold(team, args("w", because=because))
            except SystemExit as e:
                assert e.code == 2, e.code
            else:
                raise AssertionError("a hold with no reason was accepted")
        assert "held" not in json.loads(team.wo_file("w").read_text())


def test_release_of_an_unheld_work_order_is_refused():
    with tempfile.TemporaryDirectory() as d:
        team = FakeTeam(d)
        team.save_wo({"wo": "w", "zone": "Z", "tree": "/x", "base": "b"})
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                cl.cmd_wo_hold(team, args("w", release=True))
        except SystemExit as e:
            assert e.code == 2, e.code
        else:
            raise AssertionError("released a work order that was not held")


if __name__ == "__main__":
    test_hold_list_release()
    test_hold_needs_a_reason()
    test_release_of_an_unheld_work_order_is_refused()
    print("all passed")
