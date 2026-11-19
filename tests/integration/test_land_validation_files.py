"""Stage 6 reads a local kept log and routes per-file findings (D571)."""
import importlib.machinery
import importlib.util
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("CODETEAM_TEST_GROUP", "unit") != "integration",
                                reason="integration group only; run with CODETEAM_TEST_GROUP=integration")

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_validation_files", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)

C = "c" * 40
LOG_PATH = "~/land-check-logs/" + "c" * 40 + ".log"


@pytest.fixture
def kept_log(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    logs = tmp_path / "land-check-logs"
    logs.mkdir()
    (logs / (C + ".log")).write_text(
        "unrelated build output\n" * 450 +
        " ❯  engine  __tests__/mcp-daemon.test.ts (17 tests | 8 failed) 30007ms\n" +
        "\x1b[41m\x1b[1m FAIL \x1b[22m\x1b[49m \x1b[30m\x1b[46m engine \x1b[49m\x1b[39m "
        "__tests__/mcp-daemon.test.ts\x1b[2m > \x1b[22mmcp daemon\x1b[2m > \x1b[22mstarts one server\n" +
        " FAIL   engine  __tests__/daemon-older-version.test.ts > a launcher > never stops a server from a newer install\n")
    monkeypatch.setattr(cl, "all_findings", lambda team: [])
    monkeypatch.setattr(cl, "ssh", lambda *args, **kwargs: pytest.fail("local run must not use ssh"))
    return SimpleNamespace(c=lambda k, d: d, notify=lambda *a: None, manifest="m.toml", landing="landing",
                           zones={"__tests__/mcp-daemon.test.ts": ["__tests__/mcp-daemon.test.ts"]})


def test_failed_local_log_names_files_and_their_tests(kept_log):
    assert cl.validation_test_rows(kept_log, {"local": True}, C, {"result": "fail", "tail": "last output"}) == [
        {"name": "__tests__/mcp-daemon.test.ts", "result": "fail", "seconds": None,
         "failing": ["__tests__/mcp-daemon.test.ts > mcp daemon > starts one server"], "log": LOG_PATH},
        {"name": "__tests__/daemon-older-version.test.ts", "result": "fail", "seconds": None,
         "failing": ["__tests__/daemon-older-version.test.ts > a launcher > never stops a server from a newer install"],
         "log": LOG_PATH}]


def test_hung_local_log_keeps_suite_beside_files(kept_log):
    rows = cl.validation_test_rows(kept_log, {"local": True}, C, {"result": "hung", "seconds": 41, "tail": ""})
    assert rows == [
        {"name": "__tests__/mcp-daemon.test.ts", "result": "fail", "seconds": None,
         "failing": ["__tests__/mcp-daemon.test.ts > mcp daemon > starts one server"], "log": LOG_PATH},
        {"name": "__tests__/daemon-older-version.test.ts", "result": "fail", "seconds": None,
         "failing": ["__tests__/daemon-older-version.test.ts > a launcher > never stops a server from a newer install"],
         "log": LOG_PATH},
        {"name": "suite", "result": "hung", "seconds": 41,
         "failing": ["__tests__/mcp-daemon.test.ts > mcp daemon > starts one server",
                     "__tests__/daemon-older-version.test.ts > a launcher > never stops a server from a newer install"],
         "log": LOG_PATH}]


def test_a_local_tier_reads_its_kept_log_without_ssh(kept_log, tmp_path):
    (tmp_path / "land-check-logs" / (C + ".log")).write_text("FAILED ZONES: zone\n")
    rows = cl.validation_test_rows(kept_log, {"local": True, "host": "val"}, C,
                                   {"result": "fail", "tail": ""})
    assert [row["name"] for row in rows] == ["zone"]


def test_local_missing_log_falls_back_to_suite(kept_log, tmp_path):
    (tmp_path / "land-check-logs" / (C + ".log")).unlink()
    assert cl.validation_test_rows(kept_log, {"local": True}, C,
                                   {"result": "fail", "seconds": 4, "tail": ""}) == [
        {"name": "suite", "result": "fail", "seconds": 4, "log": LOG_PATH}]


def test_local_steps_use_step_rows_and_log_only_on_failures(kept_log, tmp_path):
    (tmp_path / "land-check-logs" / (C + ".log")).write_text("PASS tests a (2 s)\nFAIL tests b (3 s)\n")
    assert cl.validation_test_rows(kept_log, {"local": True, "steps": True}, C, {"result": "fail"}) == [
        {"name": "tests a", "result": "pass", "seconds": 2.0},
        {"name": "tests b", "result": "fail", "seconds": 3.0, "log": LOG_PATH}]


def test_local_file_finding_names_kept_log(kept_log, monkeypatch):
    rows = cl.validation_test_rows(kept_log, {"local": True}, C, {"result": "fail", "tail": ""})
    saved = []
    monkeypatch.setattr(cl, "load_findings", lambda team, feature: [])
    monkeypatch.setattr(cl, "save_findings", lambda team, feature, items: saved.extend(items))
    cl.open_validation_finding(kept_log, C, rows[0], "now")
    assert saved[0]["what"].endswith("; log: ~/land-check-logs/" + "c" * 40 + ".log")
