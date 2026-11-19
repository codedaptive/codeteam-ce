#!/usr/bin/env -S python3 -u
"""Contracts for a recheck whose checkout fails. Integration tests: the recheck runner and its tick
take the real stage-admission lock in a temp queue folder, and the runner its own lock and the real Lock on the
recheck rows; git and the steps are faked. The unit tests are in tests/unit/land-v52-fixes.py."""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

# Restart markers and stage admissions live beside the queue; keep them out of the checkout.
os.environ["CODETEAM_QUEUE_DIR"] = str(Path(tempfile.mkdtemp(prefix="land-queue-")) / "queue")

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_fixes", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)

# These isolated stage fixtures represent teams that have already moved over.
cl.v54_unmoved = Mock(return_value=False)


def make_team(root):
    repo = root / "repo"
    repo.mkdir()
    manifest = root / "sample.toml"
    manifest.write_text(f'repo = "{repo}"\nworktree_root = "{root / "team"}"\n'
                        '[land]\norchestrator = "Skippy"\n')
    team = cl.Team(str(manifest))
    team.notify = Mock()
    return team


def test_runner_keeps_a_failed_checkout_pending_and_retries_it():
    # A failed checkout holds every ancestor in the batch; a later successful poll completes them together.
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        rows = [{"time": "t1", "M": "first123456789", "wo": "one", "zones": ["A"], "overlapping": []},
                {"time": "t2", "M": "second12345678", "wo": "two", "zones": ["A"], "overlapping": []}]
        for wo in ("one", "two"):
            (team.dir / "wo" / f"{wo}.landed.json").write_text(json.dumps({"wo": wo, "zone": "A"}))
        (team.dir / "recheck.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
        results = team.dir / "integration-results.jsonl"
        failure = cl.CheckoutFailed("second12345678", "failed")
        with patch.object(cl, "git", return_value=SimpleNamespace(returncode=0)), \
                patch.object(cl, "itest_checkout", side_effect=[failure, failure, team.dir / "itest"]) as checkout, \
                patch.object(cl, "halted", return_value=False), \
                patch.object(cl, "recheck_steps", return_value=([], [])), patch.object(cl, "step_results", return_value=[]), \
                patch.object(cl, "apply_recheck_findings"), patch.object(cl, "after_landing") as after, \
                patch.object(cl, "now", return_value="now"):
            cl.cmd_recheck_run(team, SimpleNamespace(once=True))
            assert cl.read_recheck(team) == [rows[0], {**rows[1], "checkout_failed": "now"}]
            assert [json.loads(line).get("checkout") for line in results.read_text().splitlines()] == ["failed"]
            assert team.notify.call_count == 1
            assert all(s in team.notify.call_args.args[2] for s in ("one", "two", "stays pending"))
            cl.cmd_recheck_run(team, SimpleNamespace(once=True))
            assert cl.read_recheck(team) == [rows[0], {**rows[1], "checkout_failed": "now"}]
            assert len(results.read_text().splitlines()) == 1 and team.notify.call_count == 1
            cl.cmd_recheck_run(team, SimpleNamespace(once=True))
        assert [c.args[1] for c in checkout.call_args_list] == ["second12345678"] * 3
        assert cl.read_recheck(team) == [{**rows[0], "done": "now"},
                                        {**rows[1], "checkout_failed": "now", "done": "now"}]
        assert [json.loads(line).get("checkout") for line in results.read_text().splitlines()] == ["failed", None]
        assert json.loads(results.read_text().splitlines()[1])["batch"] == ["one", "two"]
        assert after.call_count == 2


def test_run_recheck_tick_returns_none_after_a_failed_checkout():
    # The runner sleeps a poll only when the tick returns None; a pending row that returned a job would spin.
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        row = {"time": "t1", "M": "first123456789", "wo": "one", "zones": ["A"], "overlapping": []}
        with patch.object(cl, "recheck_one", return_value={"checkout": "failed"}):
            assert cl.run_recheck_tick(team, [row]) is None
        with patch.object(cl, "recheck_one", return_value={"tests": []}):
            assert cl.run_recheck_tick(team, [row]) is not None


failed = 0
for test in [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)
             and (len(sys.argv) == 1 or k in sys.argv[1:])]:
    try:
        test()
        print(f"  PASS {test.__name__}")
    except (Exception, SystemExit) as exc:
        failed += 1
        print(f"  FAIL {test.__name__}: {type(exc).__name__}: {exc}")
print(f"{failed} failed" if failed else "all passed")
sys.exit(1 if failed else 0)
