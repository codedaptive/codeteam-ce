#!/usr/bin/env -S python3 -u
"""Stage 6 names the failing zones and tests from the validation machine's whole log.
ssh and findings are faked; nothing reaches a machine."""
import importlib.machinery
import importlib.util
import os
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_failing", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)

LOG = ("   Compiling widgetcorekit\n"
       "test dreaming::dreaming_pump_emits_think_events ... FAILED\n"
       + "test dreaming::passes ... ok\n" * 500 +
       "test intake::encode_intake_parity ... FAILED\n"
       "FAILED ZONES: WidgetCoreKit WidgetStoreKit\n")
TEAM = SimpleNamespace()


def shell_ssh(log, calls):
    """A fake ssh that runs the command it is given in a local shell, with HOME at a folder holding the log, so the
    remote grep and tail are exercised as written."""
    def fake_ssh(a, cmd, timeout=None, input=None):
        calls.append(cmd)
        with tempfile.TemporaryDirectory() as home:
            logs = Path(home) / "land-check-logs"
            logs.mkdir()
            (logs / ("c" * 40 + ".log")).write_text(log)
            r = subprocess.run(["/bin/sh", "-c", cmd], capture_output=True, text=True, timeout=timeout,
                               env=dict(os.environ, HOME=home))
        return SimpleNamespace(returncode=r.returncode, stdout=r.stdout, stderr=r.stderr)
    return fake_ssh


def rows(res, log, local=False, findings=()):
    calls = []
    with patch.object(cl, "ssh", shell_ssh(log, calls)), patch.object(cl, "all_findings", return_value=list(findings)):
        out = cl.validation_test_rows(TEAM, {"local": local}, "c" * 40, res)
    return out, calls


def test_a_remote_failure_names_its_zones_and_tests_from_the_whole_log():
    out, calls = rows({"result": "fail", "tail": "error: test failed, to rerun pass `--lib`"}, LOG)
    assert [t["name"] for t in out] == ["WidgetCoreKit", "WidgetStoreKit"], out
    assert out[0]["failing"] == ["dreaming::dreaming_pump_emits_think_events", "intake::encode_intake_parity"]
    assert len(calls) == 1 and "land-check-logs/" + "c" * 40 + ".log" in calls[0]


def test_failing_tests_alone_still_reach_the_suite_row():
    out, _ = rows({"result": "fail", "tail": ""}, "test a::b ... FAILED\n")
    assert out == [{"name": "suite", "result": "fail", "seconds": None, "failing": ["a::b"]}], out


def test_only_failure_lines_come_back_from_the_remote_read():
    with patch.object(cl, "ssh", shell_ssh(LOG + "error: 2 tests FAILED in this run\n", [])):
        got = cl.remote_failure_lines({}, "c" * 40)
    assert got.splitlines() == ["test dreaming::dreaming_pump_emits_think_events ... FAILED",
                                "test intake::encode_intake_parity ... FAILED",
                                "FAILED ZONES: WidgetCoreKit WidgetStoreKit"], got


def test_a_pass_reads_no_remote_log():
    out, calls = rows({"result": "pass", "tail": ""}, LOG)
    assert calls == [] and [t["name"] for t in out] == ["suite"]


def test_a_local_tier_reads_no_remote_log():
    out, calls = rows({"result": "fail", "tail": "FAILED ZONES: zone"}, LOG, local=True)
    assert calls == [] and [t["name"] for t in out] == ["zone"]


def test_an_unreachable_machine_falls_back_to_the_tail():
    def broken(a, cmd, timeout=None, input=None):
        raise subprocess.TimeoutExpired(cmd, timeout)
    with patch.object(cl, "ssh", broken), patch.object(cl, "all_findings", return_value=[]):
        out = cl.validation_test_rows(TEAM, {}, "c" * 40, {"result": "fail", "tail": "FAILED ZONES: A"})
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
