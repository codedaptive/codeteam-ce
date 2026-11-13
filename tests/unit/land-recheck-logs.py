#!/usr/bin/env -S python3 -u
"""A Stage 5 recheck keeps each failing step's whole log under land/recheck-logs/ and names its failing tests on the
finding and the FIX-FORWARD notice (2026-11-12: an app's failure at 730921fee0 reached the
finding with no test name and no log, and zone-tool's itest record had been overwritten by the next recheck)."""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ["CODETEAM_QUEUE_DIR"] = str(Path(tempfile.mkdtemp(prefix="land-queue-")) / "queue")

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_recheck_logs", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)
cl.v54_unmoved = Mock(return_value=False)

# The shape of a real failing run's log, cut down.
XCODEBUILD = """\
\U00100884 Test "Authenticated redirect and wrong media are refused before their paced body" recorded an issue at \
FirstPartyPinnedExchangeTests.swift:623:13: Expectation failed: await waitUntil(responder.finished, within: 30)
\U00100884 Test "Authenticated redirect and wrong media are refused before their paced body" failed after 30.026 \
seconds with 1 issue.
\U00100884 Suite "First-party client — production handshake exchange" failed after 31.642 seconds with 1 issue.
\U00100884 Test run with 14 tests in 1 suite failed after 31.643 seconds with 1 issue.
** TEST EXECUTE FAILED **
FAILED: swift run in apps/AcmeX-App exited 65; log: /x/acme-test-logs/apps_AcmeX-App.log; its last 40 lines:

Failing tests:
\tFirstPartyPinnedExchangeTests.authenticatedTransportHeadGatePrecedesBody()

** TEST EXECUTE FAILED **
"""


def test_names_from_xcodebuild_prefer_its_failing_list_over_swift_testing_display_names():
    assert cl.failing_test_names(XCODEBUILD) == ["FirstPartyPinnedExchangeTests.authenticatedTransportHeadGatePrecedesBody()"]


def test_names_from_swift_test_rust_xctest_and_pytest():
    text = "\n".join([
        "✘ Test hpkeRejects() failed after 0.012 seconds with 1 issue.",
        "✘ Test run with 9 tests failed after 0.2 seconds with 1 issue.",
        "✘ Suite HpkeTests failed after 0.1 seconds with 1 issue.",
        "test store::tests::opens_at_fixed_instant ... FAILED",
        "test store::tests::passes ... ok",
        "Test Case '-[AcmeKitTests.StoreTests testOpen]' failed (0.010 seconds).",
        "Test case 'StoreTests.testClose()' failed on 'My Mac - AcmeX (123)' (0.011 seconds)",
        "FAILED tests/unit/test_x.py::test_y - AssertionError: no",
        "FAILED ZONES: AcmeX-App",
    ])
    assert cl.failing_test_names(text) == [
        "store::tests::opens_at_fixed_instant", "AcmeKitTests.StoreTests.testOpen", "StoreTests.testClose()",
        "tests/unit/test_x.py::test_y", "hpkeRejects()"]


def make_team(root):
    repo = root / "repo"
    repo.mkdir()
    manifest = root / "sample.toml"
    manifest.write_text(f'repo = "{repo}"\nworktree_root = "{root / "team"}"\n[land]\norchestrator = "Skippy"\n')
    team = cl.Team(str(manifest))
    team.notify = Mock()
    return team


def test_a_failing_recheck_keeps_its_log_and_names_the_tests_on_the_finding():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        M = "730921fee0dabeda0e48ff2c150a7f4a31d5521c"
        row = {"M": M, "wo": "work", "overlapping": ["other"], "zones": ["AcmeX-App"]}
        (team.dir / "wo" / "work.landed.json").write_text(json.dumps({"wo": "work", "zone": "AcmeX-App"}))
        (team.dir / "recheck.jsonl").write_text(json.dumps(row) + "\n")
        name = "tests AcmeX-App (apps/AcmeX-App)"
        calls = []

        def steps(tree, batch, env, **kw):
            calls.append(kw)
            return [{"name": n, "outcome": "FAIL" if n == name else "PASS", "seconds": 1, "tail": ["last"],
                     "text": XCODEBUILD if n == name else "ok\n"} for n, _ in batch]

        with patch.object(cl, "itest_checkout", return_value=team.dir / "itest"), \
                patch.object(cl, "recheck_steps", return_value=([("type check", "c")], [(name, "t"), ("tests B (b)", "t")])), \
                patch.object(cl, "step_results", side_effect=steps), \
                patch.object(cl, "after_landing"), patch.object(cl, "now", return_value="now"):
            cl.recheck_one(team, row)
        assert all(kw.get("keep_text") for kw in calls), calls
        log = team.dir / "recheck-logs" / "730921fee0-tests-AcmeX-App-apps-AcmeX-App.log"
        assert log.read_text() == XCODEBUILD
        assert sorted(p.name for p in (team.dir / "recheck-logs").iterdir()) == [log.name]
        [result] = [json.loads(x) for x in (team.dir / "integration-results.jsonl").read_text().splitlines()]
        failed = next(t for t in result["tests"] if t["name"] == name)
        assert failed == {"name": name, "result": "fail", "seconds": 1.0, "tail": ["last"], "log": str(log),
                          "failing": ["FirstPartyPinnedExchangeTests.authenticatedTransportHeadGatePrecedesBody()"]}
        assert next(t for t in result["tests"] if t["name"] == "tests B (b)") == {
            "name": "tests B (b)", "result": "pass", "seconds": 1.0}
        [finding] = cl.load_findings(team, "work")
        assert "failing tests: FirstPartyPinnedExchangeTests.authenticatedTransportHeadGatePrecedesBody()" in finding["what"]
        assert f"log: {log}" in finding["what"]
        message = team.notify.call_args.args[2]
        assert "authenticatedTransportHeadGatePrecedesBody()" in message and str(log) in message
        # The fix tree may merge M when the cause is on landing and not in integration.
        assert "merge 730921fee0 into the fix tree" in message


def test_only_the_newest_logs_are_kept():
    with tempfile.TemporaryDirectory() as tmp:
        team = SimpleNamespace(dir=Path(tmp))
        folder = Path(tmp) / "recheck-logs"
        folder.mkdir()
        for i in range(cl.RECHECK_LOGS_KEPT + 2):
            old = folder / f"old{i:03d}.log"
            old.write_text("x")
            os.utime(old, (1000 + i, 1000 + i))
        cl.keep_recheck_logs(team, "f" * 40, [{"name": "t", "outcome": "FAIL", "seconds": 1, "tail": [], "text": "x"}])
        names = {p.name for p in folder.iterdir()}
        assert len(names) == cl.RECHECK_LOGS_KEPT and "ffffffffff-t.log" in names
        assert "old000.log" not in names and "old001.log" not in names and "old002.log" not in names


if __name__ == "__main__":
    test_names_from_xcodebuild_prefer_its_failing_list_over_swift_testing_display_names()
    test_names_from_swift_test_rust_xctest_and_pytest()
    test_a_failing_recheck_keeps_its_log_and_names_the_tests_on_the_finding()
    test_only_the_newest_logs_are_kept()
    print("all passed")
