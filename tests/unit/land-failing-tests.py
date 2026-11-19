#!/usr/bin/env -S python3 -u
"""Stage 6 names failing zones and tests from the kept log, locally or on valhost.
ssh, findings and the kept log are faked; no process starts. The cases that run the remote grep and tail in a real
/bin/sh are in tests/integration/land-failing-tests.py."""
import importlib.machinery
import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_failing", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)

TEAM = SimpleNamespace()


def rows(res, local=False, findings=()):
    with patch.object(cl, "ssh", side_effect=AssertionError("pass ssh")), \
            patch.object(cl, "all_findings", return_value=list(findings)):
        return cl.validation_test_rows(TEAM, {"local": local, "host": "val"}, "c" * 40, res)


def test_a_pass_reads_no_remote_log():
    out = rows({"result": "pass", "tail": ""})
    assert [t["name"] for t in out] == ["suite"]


def test_a_local_tier_reads_no_remote_log():
    with patch.object(cl, "kept_failure_lines", return_value=""), \
            patch.object(cl, "ssh", side_effect=AssertionError("local ssh")), \
            patch.object(cl, "all_findings", return_value=[]):
        out = cl.validation_test_rows(TEAM, {"local": True, "host": "val"}, "c" * 40,
                                      {"result": "fail", "tail": "FAILED ZONES: zone"})
    assert [t["name"] for t in out] == ["zone"]


def test_an_unreachable_machine_falls_back_to_the_tail():
    def broken(a, cmd, timeout=None, input=None):
        raise subprocess.TimeoutExpired(cmd, timeout)
    with patch.object(cl, "ssh", broken), patch.object(cl, "all_findings", return_value=[]):
        out = cl.validation_test_rows(TEAM, {"host": "val"}, "c" * 40, {"result": "fail", "tail": "FAILED ZONES: A"})
    assert [t["name"] for t in out] == ["A"] and "failing" not in out[0]


def test_the_finding_text_names_the_failing_tests():
    team = SimpleNamespace(c=lambda k, d: d, notify=lambda *a: sent.append(a), manifest="m.toml", landing="landing",
                           zones={"WidgetCoreKit": ["WidgetCoreKit"]})
    sent, saved = [], []
    with patch.object(cl, "load_findings", return_value=[]), \
            patch.object(cl, "save_findings", lambda team, feature, items: saved.extend(items)):
        cl.open_validation_finding(team, "c" * 40, {"name": "WidgetCoreKit", "result": "fail",
                                                    "failing": ["dreaming::x"]}, "now")
    assert saved[0]["zone"] == "WidgetCoreKit" and "failing tests: dreaming::x" in saved[0]["what"], saved
    assert "failing tests: dreaming::x" in sent[0][2]


VITEST = (" FAIL   engine  __tests__/daemon-older-version.test.ts > a launcher > never stops a server from a newer install\n"
          " FAIL  src/broken.test.ts [ src/broken.test.ts ]\n")
LOCAL_LOG = "~/land-check-logs/" + "c" * 40 + ".log"


def local_rows(res, log="", findings=()):
    with patch.object(cl, "kept_failure_lines", return_value=log), \
            patch.object(cl, "ssh", side_effect=AssertionError("local ssh")), \
            patch.object(cl, "all_findings", return_value=list(findings)):
        return cl.validation_test_rows(TEAM, {"local": True}, "c" * 40, res)


def test_team_vitest_failures_become_file_rows():
    assert cl.validation_tests({"result": "fail", "tail": VITEST}, None, []) == [
        {"name": "__tests__/daemon-older-version.test.ts", "result": "fail", "seconds": None,
         "failing": ["__tests__/daemon-older-version.test.ts > a launcher > never stops a server from a newer install"]},
        {"name": "src/broken.test.ts", "result": "fail", "seconds": None, "failing": []}]


def test_team_hung_vitest_keeps_suite():
    assert cl.validation_tests({"result": "hung", "seconds": 30, "tail": VITEST}, None, []) == [
        {"name": "__tests__/daemon-older-version.test.ts", "result": "fail", "seconds": None,
         "failing": ["__tests__/daemon-older-version.test.ts > a launcher > never stops a server from a newer install"]},
        {"name": "src/broken.test.ts", "result": "fail", "seconds": None, "failing": []},
        {"name": "suite", "result": "hung", "seconds": 30}]


def test_failed_zones_take_precedence_over_vitest_files():
    assert cl.validation_tests({"result": "fail", "tail": VITEST + "FAILED ZONES: core\n"}, None, []) == [
        {"name": "core", "result": "fail", "seconds": None}]


def test_local_failed_log_supplies_files_and_preserves_each_files_tests():
    assert local_rows({"result": "fail", "tail": "last line"}, VITEST) == [
        {"name": "__tests__/daemon-older-version.test.ts", "result": "fail", "seconds": None,
         "failing": ["__tests__/daemon-older-version.test.ts > a launcher > never stops a server from a newer install"],
         "log": LOCAL_LOG},
        {"name": "src/broken.test.ts", "result": "fail", "seconds": None, "failing": [], "log": LOCAL_LOG}]


def test_local_hung_log_adds_log_to_suite_and_files_not_passes():
    findings = [{"state": "open", "by": "validation", "test": "src/old.test.ts"}]
    assert local_rows({"result": "hung", "seconds": 30, "tail": ""}, VITEST, findings=findings) == [
        {"name": "__tests__/daemon-older-version.test.ts", "result": "fail", "seconds": None,
         "failing": ["__tests__/daemon-older-version.test.ts > a launcher > never stops a server from a newer install"],
         "log": LOCAL_LOG},
        {"name": "src/broken.test.ts", "result": "fail", "seconds": None, "failing": [], "log": LOCAL_LOG},
        {"name": "src/old.test.ts", "result": "pass", "seconds": None},
        {"name": "suite", "result": "hung", "seconds": 30,
         "failing": ["__tests__/daemon-older-version.test.ts > a launcher > never stops a server from a newer install"],
         "log": LOCAL_LOG}]


def test_local_pass_does_not_read_failure_log():
    with patch.object(cl, "kept_failure_lines", side_effect=AssertionError("pass read a log")), \
            patch.object(cl, "ssh", side_effect=AssertionError("local ssh")), \
            patch.object(cl, "all_findings", return_value=[]):
        assert cl.validation_test_rows(TEAM, {"local": True}, "c" * 40,
                                       {"result": "pass", "seconds": 4}) == [
            {"name": "suite", "result": "pass", "seconds": 4}]


def test_finding_and_notice_append_log_after_failing_tests():
    team = SimpleNamespace(c=lambda k, d: d, notify=lambda *a: sent.append(a), manifest="m.toml", landing="landing",
                           zones={"core": ["core"]})
    sent, saved = [], []
    with patch.object(cl, "load_findings", return_value=[]), \
            patch.object(cl, "save_findings", lambda team, feature, items: saved.extend(items)):
        cl.open_validation_finding(team, "c" * 40, {"name": "core", "result": "fail", "failing": ["a::b"],
                                                    "log": LOCAL_LOG}, "now")
    assert saved[0]["what"].endswith("; failing tests: a::b; log: " + LOCAL_LOG), saved
    assert "; failing tests: a::b; log: " + LOCAL_LOG in sent[0][2], sent


def test_finding_without_log_is_unchanged():
    team = SimpleNamespace(c=lambda k, d: d, notify=lambda *a: None, manifest="m.toml", landing="landing",
                           zones={"core": ["core"]})
    saved = []
    with patch.object(cl, "load_findings", return_value=[]), \
            patch.object(cl, "save_findings", lambda team, feature, items: saved.extend(items)):
        cl.open_validation_finding(team, "c" * 40, {"name": "core", "result": "fail"}, "now")
    assert saved[0]["what"] == "core fails in validation at C cccccccccc"


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
