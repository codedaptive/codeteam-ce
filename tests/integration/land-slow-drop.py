#!/usr/bin/env -S python3 -u
"""`finding-drop slow#N --reason` drops a slow-tests follow-up under the real findings lock,
on a temp folder's real slow-tests.json. A dropped follow-up frees its zone for the next one and can no longer be
named by --fixes; a finding id still goes to the findings files. The unit tests are tests/unit/land-slow-drop.py."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
loader = importlib.machinery.SourceFileLoader("cl_slow_drop", os.environ.get("CODETEAM_LAND", str(ROOT / "bin" / "codeteam-land")))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)


def team_at(path):
    return SimpleNamespace(dir=path, manifest="team.toml", zones={"cli": ["bin"]}, m={"assistants": []},
                           c=lambda key, default: "Orchestrator", notify=Mock(), log=Mock(), repo=path)


def flag():
    return {"total_s": 960.0, "limit_s": 900, "steps": [{"step": "tests cli (bin)", "run_s": 960.0, "queued_s": 0.0}]}


def drop(team, ident, reason="measured lock waits"):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
            patch.dict(os.environ, {"CODETEAM_SESSION": "Orc-Widgets"}), patch.object(cl, "now", return_value="NOW"):
        try:
            cl.cmd_finding_drop(team, SimpleNamespace(id=ident, reason=reason))
            code = 0
        except SystemExit as ex:
            code = ex.code
    return code, out.getvalue(), err.getvalue()


def test_drop_frees_the_zone_for_the_next_followup():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); source = {"wo": "w1", "stage": 2, "commit": "abcdefghijk"}
        first, opened = cl.open_slow_followup(team, flag(), source, "THEN", [])
        assert opened and first["id"] == "slow#1"
        assert drop(team, "slow#1") == (0, "slow#1: dropped\n", "")
        saved = json.loads((team.dir / "slow-tests.json").read_text())
        assert saved == [first | {"state": "dropped", "closed": "NOW", "reason": "measured lock waits",
                                  "dropped_by": "Orc-Widgets"}]
        second, opened = cl.open_slow_followup(team, flag(), source, "LATER", [])
        assert opened and second["id"] == "slow#2" and second["zone"] == "cli"


def test_a_dropped_followup_cannot_be_fixed():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        cl.open_slow_followup(team, flag(), {"wo": "w1", "stage": 2, "commit": "abcdefghijk"}, "THEN", [])
        drop(team, "slow#1")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            try:
                cl.tag_wo(team, {}, None, ["slow#1"])
            except SystemExit:
                pass
            else:
                raise AssertionError("a dropped follow-up was accepted by --fixes")
        assert "no open slow-tests follow-up slow#1" in err.getvalue()


def test_dropping_a_slow_id_that_is_not_open_is_refused():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        (team.dir / "slow-tests.json").write_text(json.dumps([{"id": "slow#1", "zone": "cli", "state": "closed"}]))
        for ident in ("slow#1", "slow#9"):
            code, out, err = drop(team, ident)
            assert code != 0 and out == "" and f"no open slow-tests follow-up {ident}" in err, (ident, code, err)
        assert json.loads((team.dir / "slow-tests.json").read_text()) == [{"id": "slow#1", "zone": "cli", "state": "closed"}]


def test_a_finding_id_still_drops_the_finding():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); directory = team.dir / "findings"; directory.mkdir()
        (directory / "w1.json").write_text(json.dumps([{"id": "w1#1", "state": "open"}]))
        assert drop(team, "w1#1", "not real")[:2] == (0, "w1#1: dropped\n")
        assert json.loads((directory / "w1.json").read_text())[0]["state"] == "dropped"
        assert not (team.dir / "slow-tests.json").exists()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("all passed")
