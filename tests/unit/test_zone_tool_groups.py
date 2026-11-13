"""zone-tool and the test groups when the repo's own Makefile reads GROUP.

A product's test-one reads GROUP, and its Package.swift declares the integration and validation test targets only for
their GROUP. make exports a command-line GROUP=integration to zone-tool and to the queued job, but zone-tool read
only CODETEAM_TEST_GROUP, so the record of such a run said group "unit" (and counted as unit proof at its commit),
and a clean check of the unit targets answered for a GROUP=integration run at the same code.
"""

import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def zt():
    dont_write_bytecode = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        loader = importlib.machinery.SourceFileLoader("zone_tool_groups", str(ROOT / "bin" / "zone-tool"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = dont_write_bytecode


@pytest.fixture
def env(monkeypatch):
    for name in ("CODETEAM_TEST_GROUP", "GROUP", "ZONE_CHECK", "CODETEAM_OWNS"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.mark.parametrize("test_group, group, expect", [
    (None, None, "unit"),
    (None, "integration", "integration"),
    (None, "  validation ", "validation"),
    ("integration", None, "integration"),
    ("validation", "unit", "validation"),
    ("  ", "integration", "integration"),
    (None, "  ", "unit"),
])
def test_group_reads_codeteam_test_group_then_group(zt, env, test_group, group, expect):
    if test_group is not None:
        env.setenv("CODETEAM_TEST_GROUP", test_group)
    if group is not None:
        env.setenv("GROUP", group)
    assert zt.test_group() == expect


def checks(zt, env, tmp_path):
    """run_check over pk/A with a fake ZONE_CHECK_CMD: the GROUP each real run saw, and the guard state."""
    (tmp_path / "pk" / "A").mkdir(parents=True)
    env.setenv("ZONE_CHECK_CMD", "true")
    seen = []

    def run(cmd, **kw):
        seen.append(kw["env"].get("GROUP"))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    env.setattr(subprocess, "run", run)
    return seen, {"checks": {}}


def test_a_clean_unit_check_does_not_answer_for_an_integration_run(zt, env, tmp_path):
    seen, g = checks(zt, env, tmp_path)
    assert zt.run_check(tmp_path, "pk/A", "h1", g)[0] is True
    assert zt.run_check(tmp_path, "pk/A", "h1", g)[0] is True        # the same group and code: from the cache
    assert seen == [None]
    env.setenv("GROUP", "integration")
    assert zt.run_check(tmp_path, "pk/A", "h1", g)[0] is True
    assert seen == [None, "integration"]                              # run again, with the caller's GROUP
    assert zt.run_check(tmp_path, "pk/A", "h1", g)[0] is True
    assert seen == [None, "integration"]
    env.delenv("GROUP")
    zt.run_check(tmp_path, "pk/A", "h1", g)
    assert seen == [None, "integration"]                              # unit's own clean result stands


def test_a_clean_integration_check_does_not_answer_for_a_unit_run(zt, env, tmp_path):
    seen, g = checks(zt, env, tmp_path)
    env.setenv("GROUP", "integration")
    assert zt.run_check(tmp_path, "pk/A", "h1", g)[0] is True
    env.delenv("GROUP")
    assert zt.run_check(tmp_path, "pk/A", "h1", g)[0] is True
    assert seen == ["integration", None]


def test_an_opt_in_word_is_not_a_filter_and_names_the_tests_covered(zt):
    """zone.mk's env:NAME=value word: a run with an opt-in variable on is still a whole run of
    DIR, and a pass with it off never stands for one with it on (the FAIL guard compares these words)."""
    assert zt._key_parts("one pk/A   env:ACME_X=1") == ("one", "pk/A", [])
    assert zt._key_parts("one pk/A --filter T env:ACME_X=1") == ("one", "pk/A", ["--filter", "T"])
    assert zt._key_groups("one pk/A group=integration env:ACME_X=1") == ("env:ACME_X=1", "group=integration")
    assert zt._key_groups("one pk/A env:ACME_X=1") != zt._key_groups("one pk/A")


def answered(zt, env, tmp_path, key, body_group, same_code):
    """answer_from_record for a PASS record of `key` labelled body_group, on a clean tree at commit c1: the record
    as saved afterwards, and the commit records it logged."""
    logged = []
    env.setattr(zt, "commit_state", lambda root: ("c1", True))
    env.setattr(zt, "append_commit_record", lambda root, key, rec, answered=False: logged.append(rec["group"]))
    rec = {"result": "PASS", "time": "2026-11-12T09:30:00-06:00", "hash": "h1", "group": body_group, "exit": 0}
    zt.record_path(tmp_path, key).write_text(zt.json.dumps(rec))
    assert zt.answer_from_record(tmp_path, key, dict(rec), "h1" if same_code else "h2") == 0
    return zt.json.loads(zt.record_path(tmp_path, key).read_text()), logged


@pytest.mark.parametrize("same_code", [True, False])
def test_an_old_record_labelled_unit_is_relabelled_when_it_answers(zt, env, tmp_path, same_code):
    """A record written under GROUP=integration by an older zone-tool says group "unit"; its key
    holds group=integration, so when it answers a GROUP=integration run its label is corrected and the answer is
    logged at the commit as an integration result."""
    env.setenv("GROUP", "integration")
    saved, logged = answered(zt, env, tmp_path, "one Tests/X group=integration", "unit", same_code)
    assert saved["group"] == "integration"
    assert logged == ["integration"]


def test_a_unit_record_is_left_alone(zt, env, tmp_path):
    saved, logged = answered(zt, env, tmp_path, "one Tests/X", "unit", True)
    assert saved["group"] == "unit"
    assert logged == ["unit"]
