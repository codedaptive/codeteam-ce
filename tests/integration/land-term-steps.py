#!/usr/bin/env -S python3 -u
"""An interrupted concurrent step run stops its running steps instead of waiting for them (a land
stopped by SIGTERM raised SystemExit, and the thread pool's shutdown would have waited for every running build before
the set's first tree was restored). Real processes in a temp folder: one step sleeps, the other ends as soon as the
sleeper has started, and the first result interrupts the run."""
import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_term_steps", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
sys.dont_write_bytecode = True
loader.exec_module(cl)


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def test_an_interrupted_run_stops_the_running_step():
    with tempfile.TemporaryDirectory() as d:
        pidfile, done = Path(d) / "slow.pid", Path(d) / "slow.done"
        # The slow step's pid is renamed into place, so it is never read half-written, and the quick step ends only
        # once it is there (30 s at most), so the interrupt comes after the slow step started. Before, the quick
        # result could come first on a loaded machine, and the pid file was missing or empty (load 35
        # on 18 CPUs).
        steps = [("slow", f"echo $$ > {pidfile}.tmp && mv {pidfile}.tmp {pidfile} && sleep 20 && touch {done}"),
                 ("quick", f"for i in $(seq 600); do [ -e {pidfile} ] && exit 0; sleep 0.05; done; exit 1")]

        def interrupt(result):
            raise SystemExit(143)

        try:
            cl.step_results(d, steps, dict(os.environ), on_result=interrupt)
        except SystemExit as e:
            assert e.code == 143, e.code
        else:
            raise AssertionError("the run was not interrupted")
        assert pidfile.exists(), "the slow step never wrote its pid: the quick step gave up after 30 s"
        pid = int(pidfile.read_text())
        for _ in range(100):            # the group was signalled before the pool's shutdown; it is reaped by then
            if not alive(pid):
                break
            time.sleep(0.1)
        assert not alive(pid), f"the slow step {pid} still runs"
        assert not done.exists(), "the run waited for the slow step to finish instead of stopping it"


def test_a_step_that_did_not_pass_and_reports_a_full_disk_or_a_cache_error_is_flagged():
    # What Stage 2 records as "disk" or "cache". A passing step that prints
    # the words is not flagged.
    with tempfile.TemporaryDirectory() as d:
        steps = [("full", "echo \"OSError: [Errno 28] No space left on device: '/tmp/x'\"; exit 1"),
                 ("cache", "echo '<unknown>:0: error: cannot create CAS filesystem: not a IncludeFileList node kind "
                           "[#CompilationCaching]'; exit 1"),
                 ("plain", "echo 'assert 3 == 4'; exit 1"),
                 ("passes", "echo 'checked that No space left on device is reported'; exit 0")]
        flags = {r["name"]: r.get("stopped_by") for r in cl.step_results(d, steps, dict(os.environ))}
        assert flags == {"full": "disk", "cache": "cache", "plain": None, "passes": None}, flags


if __name__ == "__main__":
    test_an_interrupted_run_stops_the_running_step()
    print("ok   an interrupted concurrent run stops its running step")
    test_a_step_that_did_not_pass_and_reports_a_full_disk_or_a_cache_error_is_flagged()
    print("ok   a step that did not pass and reports a full disk or a cache error is flagged")
